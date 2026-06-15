"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License

Container validation engine for EA Graphics Manager.
Validates parsed EA container files and generates structured reports.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from reversebox.common.logger import get_logger

from src.EA_Image.constants import (
    CONVERT_IMAGES_SUPPORTED_TYPES,
    NEW_SHAPE_ALLOWED_SIGNATURES,
    OLD_SHAPE_ALLOWED_SIGNATURES,
)

logger = get_logger(__name__)


class AnomalySeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AnomalyType(Enum):
    OUT_OF_BOUNDS = "out_of_bounds"
    ENTRY_OVERLAP = "entry_overlap"
    TRUNCATED_ENTRY = "truncated_entry"
    UNSUPPORTED_FORMAT = "unsupported_format"
    HEADER_SIZE_MISMATCH = "header_size_mismatch"
    ZERO_SIZE_ENTRY = "zero_size_entry"
    INVALID_OFFSET = "invalid_offset"
    ATTACHMENT_BOUNDS = "attachment_bounds"
    UNKNOWN_ATTACHMENT = "unknown_attachment"
    FILE_SIZE_MISMATCH = "file_size_mismatch"


@dataclass
class ValidationAnomaly:
    severity: str
    anomaly_type: str
    entry_tag: Optional[str]
    entry_id: Optional[str]
    message: str
    file_offset: int
    details: dict = field(default_factory=dict)


@dataclass
class EntrySummary:
    entry_id: str
    tag: str
    record_id: int
    entry_type: str
    start_offset: int
    end_offset: int
    data_size: int
    width: int
    height: int
    bpp: int
    is_compressed: bool
    is_supported: bool
    attachment_count: int
    anomaly_count: int = 0
    status: str = "ok"


@dataclass
class FileSummary:
    file_name: str
    file_path: str
    file_size: int
    signature: str
    endianness: str
    format_type: str
    format_version: str
    entry_count: int
    image_count: int
    attachment_total: int
    supported_count: int
    unsupported_count: int
    anomaly_warning_count: int
    anomaly_error_count: int


@dataclass
class ValidationReport:
    report_version: str = "1.0"
    timestamp: str = ""
    overall_status: str = "ok"
    file_summary: Optional[FileSummary] = None
    entry_summaries: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)

    def to_dict(self) -> dict:
        result = {
            "report_version": self.report_version,
            "timestamp": self.timestamp,
            "overall_status": self.overall_status,
            "file_summary": asdict(self.file_summary) if self.file_summary else {},
            "entries": [asdict(e) for e in self.entry_summaries],
            "anomalies": [asdict(a) for a in self.anomalies],
        }
        return result

    def export_json(self, file_path: str):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=4, sort_keys=False, ensure_ascii=False)
        logger.info(f"Validation report exported to {file_path}")

    def get_anomalies_for_entry(self, entry_id: str) -> list:
        return [a for a in self.anomalies if a.entry_id == entry_id]

    def get_anomalies_by_severity(self, severity: str) -> list:
        return [a for a in self.anomalies if a.severity == severity]


class ContainerValidator:
    """Validates a fully-parsed EAImage and produces a ValidationReport."""

    def validate(self, ea_image) -> ValidationReport:
        report = ValidationReport()
        report.timestamp = datetime.now(timezone.utc).isoformat()
        report.anomalies = []
        report.entry_summaries = []

        # 1. Build file summary
        report.file_summary = self._build_file_summary(ea_image)

        # 2. File-level checks
        self._check_file_size(ea_image, report)

        # 3. Per-entry checks
        self._check_entry_bounds(ea_image, report)
        self._check_entry_overlaps(ea_image, report)
        self._check_truncation(ea_image, report)
        self._check_unsupported(ea_image, report)
        self._check_zero_size(ea_image, report)

        # 4. Attachment checks
        self._check_attachments(ea_image, report)

        # 5. Build entry summaries and assign status
        self._build_entry_summaries(ea_image, report)

        # 6. Attach anomalies to entries
        self._attach_anomalies_to_entries(ea_image, report)

        # 7. Determine overall status
        report.overall_status = self._determine_overall_status(report)

        logger.info(
            f"Validation complete: {report.overall_status}, "
            f"{len(report.anomalies)} anomalies found"
        )
        return report

    # ------------------------------------------------------------------
    # Private check methods
    # ------------------------------------------------------------------

    def _build_file_summary(self, ea_image) -> FileSummary:
        if ea_image.sign in OLD_SHAPE_ALLOWED_SIGNATURES:
            format_type = "old_shape"
            format_version = ea_image.format_version or ""
        elif ea_image.sign in NEW_SHAPE_ALLOWED_SIGNATURES:
            format_type = "new_shape"
            format_version = str(ea_image.header_and_toc_size) if ea_image.header_and_toc_size else ""
        else:
            format_type = "unknown"
            format_version = ""

        attachment_total = sum(len(d.bin_attachments_list) for d in ea_image.dir_entry_list)
        supported_count = sum(
            1 for d in ea_image.dir_entry_list
            if d.h_record_id in CONVERT_IMAGES_SUPPORTED_TYPES
        )
        unsupported_count = len(ea_image.dir_entry_list) - supported_count

        return FileSummary(
            file_name=ea_image.f_name or "",
            file_path=ea_image.f_path or "",
            file_size=ea_image.f_size or 0,
            signature=ea_image.sign or "",
            endianness=ea_image.f_endianess_desc or "",
            format_type=format_type,
            format_version=format_version,
            entry_count=ea_image.num_of_entries,
            image_count=supported_count,
            attachment_total=attachment_total,
            supported_count=supported_count,
            unsupported_count=unsupported_count,
            anomaly_warning_count=0,
            anomaly_error_count=0,
        )

    def _check_file_size(self, ea_image, report: ValidationReport):
        """Check if declared file size matches actual file size."""
        if ea_image.total_f_size and ea_image.f_size:
            if ea_image.total_f_size != ea_image.f_size:
                # Allow CRCF tail (12 bytes)
                if abs(ea_image.total_f_size - ea_image.f_size) != 12:
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.WARNING.value,
                        anomaly_type=AnomalyType.FILE_SIZE_MISMATCH.value,
                        entry_tag=None,
                        entry_id=None,
                        message=(
                            f"Declared file size ({ea_image.total_f_size}) differs from "
                            f"actual file size ({ea_image.f_size})"
                        ),
                        file_offset=4,
                        details={
                            "declared_size": ea_image.total_f_size,
                            "actual_size": ea_image.f_size,
                        },
                    ))

    def _check_entry_bounds(self, ea_image, report: ValidationReport):
        """Check that each entry's data range is within file boundaries."""
        file_size = ea_image.f_size or ea_image.total_f_size or 0

        for ea_dir in ea_image.dir_entry_list:
            # Check start offset
            if ea_dir.start_offset is not None and ea_dir.start_offset > file_size:
                report.anomalies.append(ValidationAnomaly(
                    severity=AnomalySeverity.ERROR.value,
                    anomaly_type=AnomalyType.OUT_OF_BOUNDS.value,
                    entry_tag=ea_dir.tag,
                    entry_id=ea_dir.id,
                    message=(
                        f"Entry '{ea_dir.tag}' start offset ({ea_dir.start_offset}) "
                        f"exceeds file size ({file_size})"
                    ),
                    file_offset=ea_dir.start_offset,
                    details={"start_offset": ea_dir.start_offset, "file_size": file_size},
                ))

            # Check end offset
            if ea_dir.end_offset is not None and ea_dir.end_offset > file_size:
                report.anomalies.append(ValidationAnomaly(
                    severity=AnomalySeverity.WARNING.value,
                    anomaly_type=AnomalyType.OUT_OF_BOUNDS.value,
                    entry_tag=ea_dir.tag,
                    entry_id=ea_dir.id,
                    message=(
                        f"Entry '{ea_dir.tag}' end offset ({ea_dir.end_offset}) "
                        f"exceeds file size ({file_size})"
                    ),
                    file_offset=ea_dir.end_offset,
                    details={"end_offset": ea_dir.end_offset, "file_size": file_size},
                ))

            # Check raw data offset
            if ea_dir.raw_data_offset is not None and ea_dir.raw_data_offset > file_size:
                report.anomalies.append(ValidationAnomaly(
                    severity=AnomalySeverity.ERROR.value,
                    anomaly_type=AnomalyType.INVALID_OFFSET.value,
                    entry_tag=ea_dir.tag,
                    entry_id=ea_dir.id,
                    message=(
                        f"Entry '{ea_dir.tag}' data offset ({ea_dir.raw_data_offset}) "
                        f"exceeds file size ({file_size})"
                    ),
                    file_offset=ea_dir.raw_data_offset,
                    details={"raw_data_offset": ea_dir.raw_data_offset, "file_size": file_size},
                ))

    def _check_entry_overlaps(self, ea_image, report: ValidationReport):
        """Check for overlapping data ranges between adjacent entries."""
        entries = ea_image.dir_entry_list
        for i in range(len(entries) - 1):
            curr = entries[i]
            nxt = entries[i + 1]

            curr_end = curr.h_entry_end_offset or curr.end_offset
            if curr_end is None:
                continue
            next_start = nxt.start_offset
            if next_start is None:
                continue

            if curr_end > next_start:
                overlap_bytes = curr_end - next_start
                report.anomalies.append(ValidationAnomaly(
                    severity=AnomalySeverity.WARNING.value,
                    anomaly_type=AnomalyType.ENTRY_OVERLAP.value,
                    entry_tag=curr.tag,
                    entry_id=curr.id,
                    message=(
                        f"Entry '{curr.tag}' (end={curr_end}) overlaps with "
                        f"'{nxt.tag}' (start={next_start}) by {overlap_bytes} bytes"
                    ),
                    file_offset=next_start,
                    details={
                        "current_entry": curr.tag,
                        "current_end": curr_end,
                        "next_entry": nxt.tag,
                        "next_start": next_start,
                        "overlap_bytes": overlap_bytes,
                    },
                ))

    def _check_truncation(self, ea_image, report: ValidationReport):
        """Check if entry data appears truncated (actual read < declared size)."""
        for ea_dir in ea_image.dir_entry_list:
            if ea_dir.h_size_of_the_block and ea_dir.raw_data_size is not None:
                expected_data_size = ea_dir.h_size_of_the_block - ea_dir.header_size
                if expected_data_size > 0 and ea_dir.raw_data_size < expected_data_size:
                    deficit = expected_data_size - ea_dir.raw_data_size
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.WARNING.value,
                        anomaly_type=AnomalyType.TRUNCATED_ENTRY.value,
                        entry_tag=ea_dir.tag,
                        entry_id=ea_dir.id,
                        message=(
                            f"Entry '{ea_dir.tag}' data appears truncated: "
                            f"expected {expected_data_size} bytes, got {ea_dir.raw_data_size} bytes "
                            f"(missing {deficit} bytes)"
                        ),
                        file_offset=ea_dir.raw_data_offset or -1,
                        details={
                            "expected_size": expected_data_size,
                            "actual_size": ea_dir.raw_data_size,
                            "deficit": deficit,
                        },
                    ))

    def _check_unsupported(self, ea_image, report: ValidationReport):
        """Check for entries with unrecognized record types."""
        from src.EA_Image.dir_entry import DirEntry
        known_types = set(DirEntry.entry_types.keys())

        for ea_dir in ea_image.dir_entry_list:
            if ea_dir.h_record_id is not None:
                masked_id = ea_dir.h_record_id & 0x7F
                if masked_id not in known_types and ea_dir.h_record_id not in known_types:
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.WARNING.value,
                        anomaly_type=AnomalyType.UNSUPPORTED_FORMAT.value,
                        entry_tag=ea_dir.tag,
                        entry_id=ea_dir.id,
                        message=(
                            f"Entry '{ea_dir.tag}' has unrecognized record type "
                            f"{ea_dir.h_record_id} (0x{ea_dir.h_record_id:02X})"
                        ),
                        file_offset=ea_dir.h_entry_header_offset or -1,
                        details={"record_id": ea_dir.h_record_id},
                    ))

    def _check_zero_size(self, ea_image, report: ValidationReport):
        """Check for entries with zero data size."""
        for ea_dir in ea_image.dir_entry_list:
            if ea_dir.raw_data_size is not None and ea_dir.raw_data_size == 0:
                if ea_dir.h_size_of_the_block == 0 or ea_dir.h_size_of_the_block is None:
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.INFO.value,
                        anomaly_type=AnomalyType.ZERO_SIZE_ENTRY.value,
                        entry_tag=ea_dir.tag,
                        entry_id=ea_dir.id,
                        message=f"Entry '{ea_dir.tag}' has zero data size",
                        file_offset=ea_dir.start_offset or -1,
                        details={},
                    ))

    def _check_attachments(self, ea_image, report: ValidationReport):
        """Check binary attachment bounds and unknown types."""
        from src.EA_Image.attachments.bin_attachment_entry import BinAttachmentEntry

        known_att_types = set(BinAttachmentEntry.entry_tags.keys())

        for ea_dir in ea_image.dir_entry_list:
            entry_end = ea_dir.end_offset or 0

            for bin_att in ea_dir.bin_attachments_list:
                # Check attachment record ID
                if bin_att.h_record_id is not None and bin_att.h_record_id not in known_att_types:
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.INFO.value,
                        anomaly_type=AnomalyType.UNKNOWN_ATTACHMENT.value,
                        entry_tag=bin_att.tag,
                        entry_id=bin_att.id,
                        message=(
                            f"Unknown binary attachment type {bin_att.h_record_id} "
                            f"(0x{bin_att.h_record_id:02X}) in entry '{ea_dir.tag}'"
                        ),
                        file_offset=bin_att.start_offset or -1,
                        details={
                            "record_id": bin_att.h_record_id,
                            "parent_entry": ea_dir.tag,
                        },
                    ))

                # Check attachment bounds
                att_end = bin_att.end_offset
                if att_end is not None and entry_end > 0 and att_end > entry_end:
                    report.anomalies.append(ValidationAnomaly(
                        severity=AnomalySeverity.WARNING.value,
                        anomaly_type=AnomalyType.ATTACHMENT_BOUNDS.value,
                        entry_tag=bin_att.tag,
                        entry_id=bin_att.id,
                        message=(
                            f"Attachment '{bin_att.tag}' end offset ({att_end}) "
                            f"exceeds parent entry '{ea_dir.tag}' end ({entry_end})"
                        ),
                        file_offset=att_end,
                        details={
                            "attachment_end": att_end,
                            "parent_entry": ea_dir.tag,
                            "parent_end": entry_end,
                        },
                    ))

    def _build_entry_summaries(self, ea_image, report: ValidationReport):
        """Build EntrySummary for each directory entry and assign status."""
        warning_count = 0
        error_count = 0

        for ea_dir in ea_image.dir_entry_list:
            is_supported = ea_dir.h_record_id in CONVERT_IMAGES_SUPPORTED_TYPES
            is_compressed = False
            if ea_dir.h_is_image_compressed_masked:
                is_compressed = ea_dir.h_is_image_compressed_masked != "NONE"

            entry_anomalies = [a for a in report.anomalies if a.entry_id == ea_dir.id]

            # Determine entry status
            status = "ok"
            for anomaly in entry_anomalies:
                if anomaly.severity == AnomalySeverity.CRITICAL.value:
                    status = "error"
                    error_count += 1
                    break
                elif anomaly.severity == AnomalySeverity.ERROR.value:
                    status = "error"
                    error_count += 1
                elif anomaly.severity == AnomalySeverity.WARNING.value:
                    if status != "error":
                        status = "warning"
                        warning_count += 1

            summary = EntrySummary(
                entry_id=ea_dir.id,
                tag=ea_dir.tag,
                record_id=ea_dir.h_record_id or 0,
                entry_type=ea_dir.get_entry_type(),
                start_offset=ea_dir.start_offset or 0,
                end_offset=ea_dir.end_offset or 0,
                data_size=ea_dir.raw_data_size or 0,
                width=ea_dir.h_width or 0,
                height=ea_dir.h_height or 0,
                bpp=ea_dir.h_image_bpp or 0,
                is_compressed=is_compressed,
                is_supported=is_supported,
                attachment_count=len(ea_dir.bin_attachments_list),
                anomaly_count=len(entry_anomalies),
                status=status,
            )
            report.entry_summaries.append(summary)

        report.file_summary.anomaly_warning_count = warning_count
        report.file_summary.anomaly_error_count = error_count

    def _attach_anomalies_to_entries(self, ea_image, report: ValidationReport):
        """Attach anomaly references to corresponding DirEntry objects."""
        for anomaly in report.anomalies:
            if anomaly.entry_id:
                for ea_dir in ea_image.dir_entry_list:
                    if ea_dir.id == anomaly.entry_id:
                        ea_dir.validation_anomalies.append(anomaly)
                        break
                    for bin_att in ea_dir.bin_attachments_list:
                        if bin_att.id == anomaly.entry_id:
                            bin_att.validation_anomalies.append(anomaly)
                            break

    def _determine_overall_status(self, report: ValidationReport) -> str:
        """Determine the overall validation status from all anomalies."""
        has_critical = any(a.severity == AnomalySeverity.CRITICAL.value for a in report.anomalies)
        has_error = any(a.severity == AnomalySeverity.ERROR.value for a in report.anomalies)
        has_warning = any(a.severity == AnomalySeverity.WARNING.value for a in report.anomalies)

        if has_critical:
            return AnomalySeverity.CRITICAL.value
        elif has_error:
            return AnomalySeverity.ERROR.value
        elif has_warning:
            return AnomalySeverity.WARNING.value
        else:
            return "ok"

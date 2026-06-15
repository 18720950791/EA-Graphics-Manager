"""
Copyright © 2025  Bartłomiej Duda
License: GPL-3.0 License
"""

# Container validation for EA graphics files.
#
# This module inspects an already parsed EAImage object and produces a
# structured, JSON-serializable validation report. It aggregates basic
# container information (entry count, format, dimensions, data ranges and
# attachment info) and detects the following problems:
#   - out_of_bounds   : an offset/region points outside the file data
#   - overlap         : two entries share the same byte range
#   - truncation      : declared data is larger than what is actually present
#   - unsupported_format : an image/attachment type that can't be decoded
#
# Each problem is classified as either:
#   - "recoverable": only the affected entry is marked, loading continues
#   - "severe"     : includes the file location and a locatable reason
#
# As a side effect, every directory entry and binary attachment gets two
# extra attributes set on it: ``validation_issues`` (list of issue dicts)
# and ``validation_status`` (one of "OK" / "RECOVERABLE" / "SEVERE").

import datetime
from typing import Optional

from reversebox.common.logger import get_logger

from src.EA_Image.attachments.bin_attachment_entry import BinAttachmentEntry
from src.EA_Image.constants import CONVERT_IMAGES_SUPPORTED_TYPES, PALETTE_TYPES

logger = get_logger(__name__)

# severity levels
SEVERITY_RECOVERABLE = "recoverable"
SEVERITY_SEVERE = "severe"

# issue categories
CATEGORY_OUT_OF_BOUNDS = "out_of_bounds"
CATEGORY_OVERLAP = "overlap"
CATEGORY_TRUNCATION = "truncation"
CATEGORY_UNSUPPORTED_FORMAT = "unsupported_format"
CATEGORY_DIMENSION = "dimension"
CATEGORY_DECODE_FAILED = "decode_failed"
CATEGORY_ENTRY_COUNT = "entry_count_mismatch"
CATEGORY_SIZE_MISMATCH = "size_mismatch"
CATEGORY_UNKNOWN_ATTACHMENT = "unknown_attachment"

STATUS_OK = "OK"
STATUS_RECOVERABLE = "RECOVERABLE"
STATUS_SEVERE = "SEVERE"

# dimensions above this are treated as suspicious for an image entry
MAX_SANE_DIMENSION = 32768


def _make_issue(
    severity: str,
    category: str,
    message: str,
    entry_id: Optional[str] = None,
    entry_tag: Optional[str] = None,
    offset: Optional[int] = None,
    file_path: Optional[str] = None,
) -> dict:
    """Build a single issue record.

    For severe issues both ``file_path`` and ``offset`` are expected to be
    populated so that the problem is locatable inside the file.
    """
    return {
        "severity": severity,
        "category": category,
        "message": message,
        "entry_id": entry_id,
        "entry_tag": entry_tag,
        "offset": offset,
        "file_path": file_path,
    }


def _safe_entry_type(obj) -> str:
    try:
        return obj.get_entry_type()
    except Exception:
        return "UNKNOWN_TYPE"


def _expected_image_data_size(width: Optional[int], height: Optional[int], bpp: Optional[int]) -> Optional[int]:
    if not width or not height or not bpp:
        return None
    return (width * height * bpp + 7) // 8


def _resolve_data_length(ea_image) -> int:
    """Number of bytes actually available for the (decompressed) container."""
    if ea_image.total_f_data:
        return len(ea_image.total_f_data)
    if ea_image.total_f_size and ea_image.total_f_size > 0:
        return ea_image.total_f_size
    return ea_image.f_size or 0


def _detect_overlaps(dir_entry_list: list, file_path: str) -> dict:
    """Return a mapping of ``id(entry) -> [issue, ...]`` for overlapping entries."""
    overlap_map: dict = {}
    locatable = [e for e in dir_entry_list if e.start_offset is not None and e.end_offset is not None]
    locatable.sort(key=lambda e: e.start_offset)

    for i in range(len(locatable) - 1):
        current = locatable[i]
        nxt = locatable[i + 1]
        if current.end_offset > nxt.start_offset:
            message = (
                f"Entry '{current.tag}' (range {current.start_offset}-{current.end_offset}) overlaps "
                f"entry '{nxt.tag}' (range {nxt.start_offset}-{nxt.end_offset})"
            )
            overlap_map.setdefault(id(current), []).append(
                _make_issue(
                    SEVERITY_RECOVERABLE,
                    CATEGORY_OVERLAP,
                    message,
                    entry_id=current.id,
                    entry_tag=current.tag,
                    offset=nxt.start_offset,
                    file_path=file_path,
                )
            )
            overlap_map.setdefault(id(nxt), []).append(
                _make_issue(
                    SEVERITY_RECOVERABLE,
                    CATEGORY_OVERLAP,
                    message,
                    entry_id=nxt.id,
                    entry_tag=nxt.tag,
                    offset=nxt.start_offset,
                    file_path=file_path,
                )
            )
    return overlap_map


def _validate_attachment(att, parent_end: Optional[int], file_path: str, data_len: int, all_issues: list) -> dict:
    """Validate a single binary attachment, mark it and return its report dict."""
    issues: list = []
    record_id = att.h_record_id
    a_start = att.start_offset
    a_end = att.end_offset
    a_offset = att.raw_data_offset
    a_size = getattr(att, "raw_data_size", None)

    # out-of-bounds (severe): attachment region leaves the file data
    if a_end is not None and data_len and a_end > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Attachment '{att.tag}' ends at offset {a_end} which is beyond end of file data ({data_len})",
                entry_id=att.id,
                entry_tag=att.tag,
                offset=a_start if a_start is not None else a_end,
                file_path=file_path,
            )
        )
    elif a_end is not None and parent_end is not None and a_end > parent_end:
        # severe: attachment is declared past the end of its parent entry
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Attachment '{att.tag}' ends at offset {a_end} which is beyond its parent entry end ({parent_end})",
                entry_id=att.id,
                entry_tag=att.tag,
                offset=a_start if a_start is not None else a_end,
                file_path=file_path,
            )
        )

    # unknown / unsupported attachment type (recoverable)
    known = record_id in BinAttachmentEntry.entry_tags or record_id in PALETTE_TYPES
    if not known:
        issues.append(
            _make_issue(
                SEVERITY_RECOVERABLE,
                CATEGORY_UNKNOWN_ATTACHMENT,
                f"Attachment '{att.tag}' has an unknown record id {record_id}",
                entry_id=att.id,
                entry_tag=att.tag,
                offset=a_start,
                file_path=file_path,
            )
        )

    att.validation_issues = issues
    att.validation_status = _status_from_issues(issues)
    all_issues.extend(issues)

    return {
        "id": att.id,
        "tag": att.tag,
        "record_id": record_id,
        "format": _safe_entry_type(att),
        "offset_range": {"start": a_start, "end": a_end},
        "data_offset": a_offset,
        "data_size": a_size,
        "size_of_block": att.h_size_of_the_block,
        "status": att.validation_status,
        "issues": issues,
    }


def _validate_dir_entry(de, file_path: str, data_len: int, preset_issues: list, all_issues: list) -> dict:
    """Validate a single directory entry, mark it and return its report dict."""
    issues: list = list(preset_issues)  # overlap issues detected earlier

    record_id = de.h_record_id
    fmt = _safe_entry_type(de)
    width = de.h_width
    height = de.h_height
    bpp = de.h_image_bpp
    start = de.start_offset
    end = de.end_offset
    data_offset = de.raw_data_offset
    data_size = de.raw_data_size
    data_end = (data_offset + data_size) if (data_offset is not None and data_size is not None) else None
    header_offset = de.h_entry_header_offset
    header_size = de.header_size
    size_of_block = de.h_size_of_the_block
    compression = de.h_is_image_compressed_masked

    # unsupported image format (recoverable - other entries still load)
    if record_id not in CONVERT_IMAGES_SUPPORTED_TYPES:
        issues.append(
            _make_issue(
                SEVERITY_RECOVERABLE,
                CATEGORY_UNSUPPORTED_FORMAT,
                f"Image format '{fmt}' is not supported for decoding/preview",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=header_offset,
                file_path=file_path,
            )
        )

    # out-of-bounds checks (severe)
    if data_offset is not None and data_len and data_offset > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Data offset {data_offset} is beyond end of file data ({data_len})",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=data_offset,
                file_path=file_path,
            )
        )
    elif data_end is not None and data_len and data_end > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Image data ends at offset {data_end} which is beyond end of file data ({data_len})",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=data_offset,
                file_path=file_path,
            )
        )

    if end is not None and data_len and end > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Entry end offset {end} is beyond end of file data ({data_len})",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=start if start is not None else end,
                file_path=file_path,
            )
        )

    if header_offset is not None and header_size and (header_offset + header_size) > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_OUT_OF_BOUNDS,
                f"Entry header at offset {header_offset} (size {header_size}) extends beyond end of file data ({data_len})",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=header_offset,
                file_path=file_path,
            )
        )

    # truncation: declared block extends past the file end (severe)
    if size_of_block and start is not None and (start + size_of_block) > data_len:
        issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_TRUNCATION,
                f"Declared block size {size_of_block} at offset {start} extends beyond end of file data ({data_len})",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=start,
                file_path=file_path,
            )
        )

    # truncation: uncompressed image payload smaller than expected (recoverable)
    expected = _expected_image_data_size(width, height, bpp)
    if (
        expected is not None
        and data_size is not None
        and record_id in CONVERT_IMAGES_SUPPORTED_TYPES
        and compression in (None, "NONE")
        and data_size < expected
    ):
        issues.append(
            _make_issue(
                SEVERITY_RECOVERABLE,
                CATEGORY_TRUNCATION,
                f"Image data is truncated: {data_size} bytes present but {expected} expected for "
                f"{width}x{height} @ {bpp}bpp",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=data_offset,
                file_path=file_path,
            )
        )

    # suspicious dimensions (recoverable)
    if record_id in CONVERT_IMAGES_SUPPORTED_TYPES:
        if width == 0 or height == 0:
            issues.append(
                _make_issue(
                    SEVERITY_RECOVERABLE,
                    CATEGORY_DIMENSION,
                    f"Image has a zero dimension ({width}x{height})",
                    entry_id=de.id,
                    entry_tag=de.tag,
                    offset=header_offset,
                    file_path=file_path,
                )
            )
        elif (width and width > MAX_SANE_DIMENSION) or (height and height > MAX_SANE_DIMENSION):
            issues.append(
                _make_issue(
                    SEVERITY_RECOVERABLE,
                    CATEGORY_DIMENSION,
                    f"Image has suspiciously large dimensions ({width}x{height})",
                    entry_id=de.id,
                    entry_tag=de.tag,
                    offset=header_offset,
                    file_path=file_path,
                )
            )

    # decoding failure recorded during conversion (recoverable)
    conversion_error = getattr(de, "conversion_error", None)
    if conversion_error:
        issues.append(
            _make_issue(
                SEVERITY_RECOVERABLE,
                CATEGORY_DECODE_FAILED,
                f"Image could not be decoded: {conversion_error}",
                entry_id=de.id,
                entry_tag=de.tag,
                offset=data_offset,
                file_path=file_path,
            )
        )

    # attachments
    attachment_reports: list = []
    for att in de.bin_attachments_list:
        attachment_reports.append(_validate_attachment(att, end, file_path, data_len, all_issues))

    de.validation_issues = issues
    de.validation_status = _status_from_issues(issues)
    all_issues.extend(issues)

    return {
        "id": de.id,
        "tag": de.tag,
        "record_id": record_id,
        "format": fmt,
        "width": width,
        "height": height,
        "bpp": bpp,
        "size_of_block": size_of_block,
        "compression": compression,
        "offset_range": {"start": start, "end": end},
        "data_range": {"offset": data_offset, "size": data_size, "end": data_end},
        "attachment_count": len(attachment_reports),
        "attachments": attachment_reports,
        "status": de.validation_status,
        "issues": issues,
    }


def _status_from_issues(issues: list) -> str:
    if any(issue["severity"] == SEVERITY_SEVERE for issue in issues):
        return STATUS_SEVERE
    if issues:
        return STATUS_RECOVERABLE
    return STATUS_OK


def validate_ea_image(ea_image) -> dict:
    """Validate a parsed EAImage object and return a JSON-serializable report.

    Each directory entry and attachment is also marked in-place with
    ``validation_issues`` and ``validation_status`` so the GUI can flag them.
    """
    file_path = ea_image.f_path
    data_len = _resolve_data_length(ea_image)
    declared_size = ea_image.total_f_size

    all_issues: list = []

    # file-level: declared vs parsed entry count (severe - structural problem)
    declared_count = ea_image.num_of_entries
    parsed_count = len(ea_image.dir_entry_list)
    if declared_count is not None and declared_count >= 0 and declared_count != parsed_count:
        all_issues.append(
            _make_issue(
                SEVERITY_SEVERE,
                CATEGORY_ENTRY_COUNT,
                f"Header declares {declared_count} entries but {parsed_count} were parsed",
                offset=8,  # num_of_entries field follows the 4-byte signature + 4-byte size
                file_path=file_path,
            )
        )

    # file-level: declared total size vs actual data length (recoverable / informational)
    if declared_size and data_len and declared_size != data_len:
        all_issues.append(
            _make_issue(
                SEVERITY_RECOVERABLE,
                CATEGORY_SIZE_MISMATCH,
                f"Header declares total size {declared_size} but {data_len} bytes are available",
                offset=4,  # total file size field follows the 4-byte signature
                file_path=file_path,
            )
        )

    overlap_map = _detect_overlaps(ea_image.dir_entry_list, file_path)

    entry_reports: list = []
    attachment_count = 0
    for de in ea_image.dir_entry_list:
        preset = overlap_map.get(id(de), [])
        entry_report = _validate_dir_entry(de, file_path, data_len, preset, all_issues)
        attachment_count += entry_report["attachment_count"]
        entry_reports.append(entry_report)

    severe_count = sum(1 for issue in all_issues if issue["severity"] == SEVERITY_SEVERE)
    recoverable_count = sum(1 for issue in all_issues if issue["severity"] == SEVERITY_RECOVERABLE)

    issues_by_category: dict = {}
    for issue in all_issues:
        issues_by_category[issue["category"]] = issues_by_category.get(issue["category"], 0) + 1

    report = {
        "tool": "EA Graphics Manager",
        "report_type": "container_validation",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "file": {
            "name": ea_image.f_name,
            "path": file_path,
            "signature": ea_image.sign,
            "format_version": ea_image.format_version,
            "endianness": ea_image.f_endianess_desc,
            "compressed_on_disk": ea_image.is_total_f_data_compressed,
            "declared_total_size": declared_size,
            "actual_data_size": data_len,
            "declared_entry_count": declared_count,
            "parsed_entry_count": parsed_count,
        },
        "summary": {
            "entry_count": parsed_count,
            "attachment_count": attachment_count,
            "issue_count": len(all_issues),
            "severe_count": severe_count,
            "recoverable_count": recoverable_count,
            "issues_by_category": issues_by_category,
            "status": "ISSUES_FOUND" if all_issues else STATUS_OK,
        },
        "entries": entry_reports,
        "issues": all_issues,
    }

    logger.info(
        f"Validation report for '{ea_image.f_name}': {parsed_count} entries, "
        f"{len(all_issues)} issue(s) ({severe_count} severe, {recoverable_count} recoverable)"
    )
    return report

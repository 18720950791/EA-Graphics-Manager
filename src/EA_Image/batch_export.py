"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from reversebox.common.logger import get_logger
from reversebox.image.pillow_wrapper import PillowWrapper

from src.EA_Image.constants import CONVERT_IMAGES_SUPPORTED_TYPES

logger = get_logger(__name__)

# Export format identifiers used across the batch export feature
EXPORT_FORMAT_DDS = "DDS"
EXPORT_FORMAT_PNG = "PNG"
EXPORT_FORMAT_BMP = "BMP"
EXPORT_FORMAT_RAW = "RAW"

# Formats that decode the image and write a real picture file
IMAGE_EXPORT_FORMATS = (EXPORT_FORMAT_DDS, EXPORT_FORMAT_PNG, EXPORT_FORMAT_BMP)

_FORMAT_EXTENSIONS = {
    EXPORT_FORMAT_DDS: ".dds",
    EXPORT_FORMAT_PNG: ".png",
    EXPORT_FORMAT_BMP: ".bmp",
    EXPORT_FORMAT_RAW: ".bin",
}

# Characters that are not allowed in filenames on Windows (and best avoided everywhere)
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'


def get_extension_for_format(export_format: str) -> str:
    """Return the file extension (including the leading dot) for a given export format."""
    return _FORMAT_EXTENSIONS.get(export_format, ".bin")


def sanitize_filename(name: Optional[str]) -> str:
    """Turn an arbitrary string into a safe filename fragment (no path separators or reserved chars)."""
    if not name:
        return ""
    cleaned = "".join("_" if (char in _INVALID_FILENAME_CHARS or ord(char) < 32) else char for char in name)
    # Windows does not allow names ending with a space or a dot
    return cleaned.strip(" .")


def build_unique_filename(out_dir: str, base_name: str, extension: str, used_names: set) -> str:
    """
    Build a filename that is stable for a given base name but never overwrites an existing file.

    The first candidate is simply ``base_name + extension``. If that name is already taken
    (either earlier in the same batch or by a file already on disk) a numeric suffix is appended
    (``_001``, ``_002``, ...) until a free name is found. ``used_names`` is updated in place.
    """
    safe_base = sanitize_filename(base_name) or "image"
    candidate = safe_base + extension
    counter = 1
    while candidate.lower() in used_names or os.path.exists(os.path.join(out_dir, candidate)):
        candidate = f"{safe_base}_{counter:03d}{extension}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def is_entry_image_exportable(ea_dir) -> bool:
    """Return True if the dir entry can be exported as a decoded image (PNG/DDS/BMP)."""
    record_id = getattr(ea_dir, "h_record_id", None)
    if record_id not in CONVERT_IMAGES_SUPPORTED_TYPES:
        return False
    if not getattr(ea_dir, "is_img_convert_supported", False):
        return False
    if not getattr(ea_dir, "img_convert_data", None):
        return False
    return True


def get_entry_export_bytes(ea_dir, export_format: str) -> bytes:
    """
    Return the bytes that should be written to disk for a single dir entry.

    Raises ``ValueError`` if the entry cannot be exported in the requested format, so the
    caller can record the reason and continue with the remaining entries.
    """
    if export_format == EXPORT_FORMAT_RAW:
        raw_data = getattr(ea_dir, "raw_data", None)
        if not raw_data:
            raise ValueError("Entry has no raw data to export")
        return raw_data

    if export_format in IMAGE_EXPORT_FORMATS:
        if not is_entry_image_exportable(ea_dir):
            record_id = getattr(ea_dir, "h_record_id", "?")
            raise ValueError(f"Image type {record_id} is not supported for image export")
        out_data = PillowWrapper().get_pil_image_file_data_for_export(
            ea_dir.img_convert_data, ea_dir.h_width, ea_dir.h_height, pillow_format=export_format
        )
        if not out_data:
            raise ValueError("Converted image data is empty")
        return out_data

    raise ValueError(f"Unknown export format: {export_format}")


@dataclass
class BatchExportItem:
    """A single entry queued for batch export."""

    container_name: str  # e.g. "awards.ssh"
    entry_index: int  # 1-based index of the entry within its container (stable across sessions)
    entry_tag: str  # human-readable tag of the entry
    ea_dir: object  # the DirEntry object holding the data


@dataclass
class BatchExportEntryResult:
    """Outcome for a single entry after a batch export run."""

    name: str  # final filename (on success) or display name (on skip/failure)
    entry_id: str
    status: str  # "exported" | "skipped" | "failed"
    reason: str = ""


@dataclass
class BatchExportResult:
    """Aggregated result of a batch export run."""

    out_dir: str
    export_format: str
    total: int = 0
    exported: List[BatchExportEntryResult] = field(default_factory=list)
    skipped: List[BatchExportEntryResult] = field(default_factory=list)
    failed: List[BatchExportEntryResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def exported_count(self) -> int:
        return len(self.exported)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    def has_problems(self) -> bool:
        return bool(self.skipped or self.failed)

    def summary_text(self) -> str:
        parts = [
            f"Exported: {self.exported_count}",
            f"Skipped: {self.skipped_count}",
            f"Failed: {self.failed_count}",
        ]
        if self.cancelled:
            parts.append("(cancelled)")
        return "   |   ".join(parts)

    def report_text(self) -> str:
        lines = [
            f"Batch export report (format: {self.export_format})",
            f"Output directory: {self.out_dir}",
            f"Total entries: {self.total}",
            self.summary_text(),
        ]
        if self.cancelled:
            lines.append("NOTE: Export was cancelled before processing all entries.")
        if self.skipped:
            lines.append("")
            lines.append("Skipped entries:")
            for entry in self.skipped:
                lines.append(f"  - {entry.entry_id} ({entry.name}): {entry.reason}")
        if self.failed:
            lines.append("")
            lines.append("Failed entries:")
            for entry in self.failed:
                lines.append(f"  - {entry.entry_id} ({entry.name}): {entry.reason}")
        return "\n".join(lines) + "\n"


def build_base_name(item: BatchExportItem) -> str:
    """
    Build a stable base filename for an entry.

    The name is derived from the container name plus the entry's 1-based index within that
    container, so the same entry always maps to the same base name across sessions. The entry
    tag is appended when it adds useful information.
    """
    stem = sanitize_filename(os.path.splitext(item.container_name or "container")[0]) or "container"
    base = f"{stem}_{item.entry_index:03d}"
    tag = sanitize_filename(item.entry_tag)
    if tag and tag.lower() != stem.lower():
        base = f"{base}_{tag}"
    return base


def run_batch_export(
    items: List[BatchExportItem],
    out_dir: str,
    export_format: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> BatchExportResult:
    """
    Export every item in ``items`` to ``out_dir`` using ``export_format``.

    Unsupported entries are recorded as skipped and entries that raise an error are recorded
    as failed; in both cases the remaining entries continue to be processed. ``progress_callback``
    (if given) is called with ``(current_index, total, display_name)`` before each entry, and
    ``cancel_check`` (if given) is polled before each entry so the run can stop early.
    """
    result = BatchExportResult(out_dir=out_dir, export_format=export_format, total=len(items))
    used_names: set = set()
    extension = get_extension_for_format(export_format)
    total = len(items)

    for index, item in enumerate(items, start=1):
        if cancel_check is not None and cancel_check():
            result.cancelled = True
            logger.info("Batch export cancelled by user")
            break

        ea_dir = item.ea_dir
        entry_id = str(getattr(ea_dir, "id", index))
        display_name = item.entry_tag or entry_id

        if progress_callback is not None:
            progress_callback(index, total, display_name)

        # Skip entries that cannot be exported in the chosen image format without aborting the batch
        if export_format in IMAGE_EXPORT_FORMATS and not is_entry_image_exportable(ea_dir):
            record_id = getattr(ea_dir, "h_record_id", "?")
            reason = f"Image type {record_id} is not supported for image export"
            result.skipped.append(BatchExportEntryResult(display_name, entry_id, "skipped", reason))
            logger.warning(f"Skipping entry {entry_id}: {reason}")
            continue

        try:
            out_data = get_entry_export_bytes(ea_dir, export_format)
            filename = build_unique_filename(out_dir, build_base_name(item), extension, used_names)
            out_path = os.path.join(out_dir, filename)
            with open(out_path, "wb") as out_file:
                out_file.write(out_data)
            result.exported.append(BatchExportEntryResult(filename, entry_id, "exported"))
            logger.info(f"Exported entry {entry_id} -> {out_path}")
        except Exception as error:
            reason = str(error)
            result.failed.append(BatchExportEntryResult(display_name, entry_id, "failed", reason))
            logger.error(f"Failed to export entry {entry_id}: {reason}")

    return result


def write_report_file(result: BatchExportResult, out_dir: str, report_filename: str = "_export_report.txt") -> Optional[str]:
    """Write a failure/skip report to ``out_dir`` when there is something worth reporting.

    Returns the report path, or ``None`` if no report was needed or writing failed.
    """
    if not result.has_problems() and not result.cancelled:
        return None
    report_path = os.path.join(out_dir, report_filename)
    try:
        with open(report_path, "w", encoding="utf-8") as report_file:
            report_file.write(result.report_text())
        return report_path
    except Exception as error:
        logger.error(f"Failed to write export report: {error}")
        return None

"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License

Batch export engine for EA Graphics Manager.
Pure Python module with zero tkinter imports.
"""

import os
import queue
import re
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import List, Optional

from reversebox.common.logger import get_logger
from reversebox.image.pillow_wrapper import PillowWrapper

from src.EA_Image.dir_entry import DirEntry
from src.EA_Image.ea_image_main import EAImage

logger = get_logger(__name__)

# Queue message types
MSG_PROGRESS: str = "PROGRESS"
MSG_LOG: str = "LOG"
MSG_COMPLETE: str = "COMPLETE"
MSG_ERROR: str = "ERROR"


@dataclass
class ExportItem:
    """Per-entry export result."""

    entry_id: str
    entry_tag: str
    entry_index: int
    status: str  # "ok" | "skipped" | "failed"
    output_path: str = ""
    skip_reason: str = ""
    error_message: str = ""


@dataclass
class BatchExportResult:
    """Aggregate result of a batch export operation."""

    ea_image_name: str
    total_entries: int
    exported_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    cancelled: bool = False
    items: List[ExportItem] = field(default_factory=list)
    output_dir: str = ""
    elapsed_seconds: float = 0.0


def _sanitize_tag(tag: str) -> str:
    """Sanitize an entry tag for use in filenames."""
    if not tag:
        return "entry"
    safe = re.sub(r"[^\w\-.]", "_", tag)
    safe = re.sub(r"_+", "_", safe)
    safe = safe.strip("_")
    return safe if safe else "entry"


def generate_filename(
    ea_image: EAImage,
    ea_dir: DirEntry,
    entry_index: int,
    file_format: str,
    used_names: set,
) -> str:
    """
    Generate a stable, unique filename for an export entry.

    Pattern: {base}_{zero_padded_index}_{sanitized_tag}.{format}
    Example: awards_001_PAL8.dds
    """
    base_name = os.path.splitext(ea_image.f_name)[0]

    # Zero-pad index, scale width for large files (min 3 digits)
    pad_width = max(len(str(ea_image.num_of_entries)), 3)
    index_str = str(entry_index).zfill(pad_width)

    safe_tag = _sanitize_tag(ea_dir.tag)

    candidate = f"{base_name}_{index_str}_{safe_tag}.{file_format}"

    # Deduplicate (case-insensitive)
    counter = 1
    original = candidate
    while candidate.lower() in used_names:
        counter += 1
        name_part = os.path.splitext(original)[0]
        candidate = f"{name_part}_{counter}.{file_format}"

    used_names.add(candidate.lower())
    return candidate


class BatchExportEngine:
    """
    Core export logic. Iterates over EAImage directory entries,
    exports each to the chosen format, and reports progress via queue.
    """

    def __init__(
        self,
        ea_image: EAImage,
        output_dir: str,
        file_format: str,
        msg_queue: queue.Queue,
        stop_event: threading.Event,
    ):
        self.ea_image = ea_image
        self.output_dir = output_dir
        self.file_format = file_format  # "dds", "png", "bmp", or "bin"
        self.msg_queue = msg_queue
        self.stop_event = stop_event

    def execute(self) -> BatchExportResult:
        """Main export loop. Returns aggregate result."""
        start_time = time.time()
        result = BatchExportResult(
            ea_image_name=self.ea_image.f_name,
            total_entries=self.ea_image.num_of_entries,
            output_dir=self.output_dir,
        )

        is_raw_mode = self.file_format == "bin"
        used_names: set = set()
        pillow_wrapper: Optional[PillowWrapper] = None

        if not is_raw_mode:
            pillow_wrapper = PillowWrapper()

        # Validate output directory
        if not os.path.isdir(self.output_dir):
            try:
                os.makedirs(self.output_dir, exist_ok=True)
            except OSError as e:
                self.msg_queue.put(
                    (MSG_ERROR, {"message": f"Cannot create output directory: {e}", "traceback": traceback.format_exc()})
                )
                result.elapsed_seconds = time.time() - start_time
                return result

        for idx, ea_dir in enumerate(self.ea_image.dir_entry_list, start=1):
            # Check cancellation between entries
            if self.stop_event.is_set():
                result.cancelled = True
                break

            entry_tag = ea_dir.tag or f"entry_{idx}"

            # Skip unsupported entries in image mode
            if not is_raw_mode and not ea_dir.is_img_convert_supported:
                item = ExportItem(
                    entry_id=ea_dir.id,
                    entry_tag=entry_tag,
                    entry_index=idx,
                    status="skipped",
                    skip_reason=f"Image type {ea_dir.h_record_id} not supported for conversion",
                )
                result.items.append(item)
                result.skipped_count += 1
                self.msg_queue.put(
                    (
                        MSG_PROGRESS,
                        {
                            "current": idx,
                            "total": result.total_entries,
                            "entry_tag": entry_tag,
                            "status": "skipped",
                            "detail": item.skip_reason,
                        },
                    )
                )
                continue

            # Generate filename
            ext = self.file_format if is_raw_mode else self.file_format
            filename = generate_filename(self.ea_image, ea_dir, idx, ext, used_names)
            output_path = os.path.join(self.output_dir, filename)

            # Export
            try:
                if is_raw_mode:
                    self._export_single_raw(ea_dir, output_path)
                else:
                    self._export_single_image(ea_dir, output_path, pillow_wrapper)

                item = ExportItem(
                    entry_id=ea_dir.id,
                    entry_tag=entry_tag,
                    entry_index=idx,
                    status="ok",
                    output_path=output_path,
                )
                result.items.append(item)
                result.exported_count += 1
                self.msg_queue.put(
                    (
                        MSG_PROGRESS,
                        {
                            "current": idx,
                            "total": result.total_entries,
                            "entry_tag": entry_tag,
                            "status": "ok",
                            "detail": filename,
                        },
                    )
                )
            except Exception as e:
                error_msg = str(e)
                item = ExportItem(
                    entry_id=ea_dir.id,
                    entry_tag=entry_tag,
                    entry_index=idx,
                    status="failed",
                    error_message=error_msg,
                )
                result.items.append(item)
                result.failed_count += 1
                self.msg_queue.put(
                    (
                        MSG_PROGRESS,
                        {
                            "current": idx,
                            "total": result.total_entries,
                            "entry_tag": entry_tag,
                            "status": "failed",
                            "detail": error_msg,
                        },
                    )
                )
                logger.error(f"Failed to export entry {idx} ({entry_tag}): {e}")

        if pillow_wrapper is not None:
            del pillow_wrapper

        result.elapsed_seconds = time.time() - start_time
        return result

    def _export_single_image(self, ea_dir: DirEntry, output_path: str, pillow_wrapper: PillowWrapper) -> None:
        """Convert DirEntry RGBA data to DDS/PNG/BMP and write to file. Raises on failure."""
        if not ea_dir.img_convert_data:
            raise ValueError("Empty image convert data")

        file_ext_upper = self.file_format.upper()
        out_data = pillow_wrapper.get_pil_image_file_data_for_export(
            ea_dir.img_convert_data,
            ea_dir.h_width,
            ea_dir.h_height,
            pillow_format=file_ext_upper,
        )
        if not out_data:
            raise ValueError("PillowWrapper returned empty image data")

        with open(output_path, "wb") as f:
            f.write(out_data)

        logger.info(f"Exported image: {output_path}")

    def _export_single_raw(self, ea_dir: DirEntry, output_path: str) -> None:
        """Write raw entry data to .bin file. Raises on failure."""
        if not ea_dir.raw_data:
            raise ValueError("Empty raw data")

        with open(output_path, "wb") as f:
            f.write(ea_dir.raw_data)

        logger.info(f"Exported raw data: {output_path}")


class BatchExportWorker(threading.Thread):
    """Daemon thread wrapper around BatchExportEngine."""

    def __init__(
        self,
        ea_image: EAImage,
        output_dir: str,
        file_format: str,
        msg_queue: queue.Queue,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.ea_image = ea_image
        self.output_dir = output_dir
        self.file_format = file_format
        self.msg_queue = msg_queue
        self.stop_event = stop_event

    def run(self) -> None:
        """Create engine, execute export, put result on queue."""
        try:
            engine = BatchExportEngine(
                self.ea_image,
                self.output_dir,
                self.file_format,
                self.msg_queue,
                self.stop_event,
            )
            result = engine.execute()
            self.msg_queue.put((MSG_COMPLETE, result))
        except Exception as e:
            self.msg_queue.put(
                (
                    MSG_ERROR,
                    {
                        "message": f"Fatal export error: {e}",
                        "traceback": traceback.format_exc(),
                    },
                )
            )
            logger.error(f"Batch export worker error: {e}")

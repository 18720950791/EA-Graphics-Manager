"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License

Batch export dialog for EA Graphics Manager.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

import center_tk_window
from reversebox.common.logger import get_logger

from src.EA_Image.constants import CONVERT_IMAGES_SUPPORTED_TYPES
from src.EA_Image.ea_image_main import EAImage
from src.export.batch_export_engine import (
    MSG_COMPLETE,
    MSG_ERROR,
    MSG_LOG,
    MSG_PROGRESS,
    BatchExportResult,
    BatchExportWorker,
)

logger = get_logger(__name__)

BATCH_WINDOW_WIDTH = 550
BATCH_WINDOW_HEIGHT = 520


class BatchExportDialog:
    """Batch export dialog with config and progress phases."""

    def __init__(self, gui_main, ea_image: EAImage, export_mode: str = "images"):
        """
        Args:
            gui_main: EAManGui instance
            ea_image: Target EAImage to export from
            export_mode: "images" or "raw"
        """
        self.gui_main = gui_main
        self.ea_image = ea_image
        self.export_mode = export_mode

        self.msg_queue: queue.Queue = queue.Queue()
        self.stop_event: threading.Event = threading.Event()
        self.worker: Optional[BatchExportWorker] = None
        self._export_finished: bool = True

        self._create_window()
        self._create_widgets()

    def _create_window(self) -> None:
        """Create the Toplevel window."""
        self.batch_window = tk.Toplevel(width=BATCH_WINDOW_WIDTH, height=BATCH_WINDOW_HEIGHT)
        self.batch_window.wm_title("Batch Export")
        self.batch_window.minsize(BATCH_WINDOW_WIDTH, BATCH_WINDOW_HEIGHT)
        self.batch_window.maxsize(BATCH_WINDOW_WIDTH, BATCH_WINDOW_HEIGHT)
        self.batch_window.resizable(False, False)
        self.batch_window.wm_attributes("-toolwindow", "True")
        self.batch_window.attributes("-topmost", "true")
        self.batch_window.protocol("WM_DELETE_WINDOW", self._close_dialog)

        self.main_frame = tk.Frame(self.batch_window, bg="#f0f0f0")
        self.main_frame.place(x=0, y=0, relwidth=1, relheight=1)

    def _create_widgets(self) -> None:
        """Create all dialog widgets."""
        self._create_source_frame()
        self._create_format_frame()
        self._create_directory_frame()
        self._create_progress_frame()
        self._create_button_frame()

    def _create_source_frame(self) -> None:
        """Create source file info display."""
        self.source_frame = tk.LabelFrame(
            self.main_frame, text="Source File", bg="#f0f0f0", padx=5, pady=5
        )
        self.source_frame.place(x=10, y=10, width=530, height=80)

        total, exportable, unsupported = self._count_exportable_entries()

        tk.Label(
            self.source_frame,
            text=f"File: {self.ea_image.f_name}",
            bg="#f0f0f0",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).place(x=5, y=2, width=500, height=20)

        tk.Label(
            self.source_frame,
            text=f"Total entries: {total}  |  Exportable: {exportable}  |  Unsupported: {unsupported}",
            bg="#f0f0f0",
            font=("Segoe UI", 9),
            anchor="w",
        ).place(x=5, y=25, width=500, height=20)

        mode_text = "Image Export (DDS/PNG/BMP)" if self.export_mode == "images" else "Raw Data Export (.bin)"
        tk.Label(
            self.source_frame,
            text=f"Mode: {mode_text}",
            bg="#f0f0f0",
            font=("Segoe UI", 9),
            anchor="w",
        ).place(x=5, y=48, width=500, height=20)

    def _create_format_frame(self) -> None:
        """Create format selection radiobuttons."""
        self.format_frame = tk.LabelFrame(
            self.main_frame, text="Export Format", bg="#f0f0f0", padx=5, pady=5
        )
        self.format_frame.place(x=10, y=100, width=530, height=70)

        self.format_var = tk.StringVar(value="dds")

        if self.export_mode == "images":
            formats = [("DDS", "dds"), ("PNG", "png"), ("BMP", "bmp"), ("Raw .bin", "bin")]
        else:
            formats = [("Raw .bin", "bin")]
            self.format_var.set("bin")

        x_pos = 10
        for label, value in formats:
            rb = tk.Radiobutton(
                self.format_frame,
                text=label,
                variable=self.format_var,
                value=value,
                bg="#f0f0f0",
                font=("Segoe UI", 9),
            )
            rb.place(x=x_pos, y=5, width=100, height=25)
            if self.export_mode == "raw" and value != "bin":
                rb.config(state="disabled")
            x_pos += 120

    def _create_directory_frame(self) -> None:
        """Create output directory picker."""
        self.dir_frame = tk.LabelFrame(
            self.main_frame, text="Output Directory", bg="#f0f0f0", padx=5, pady=5
        )
        self.dir_frame.place(x=10, y=180, width=530, height=65)

        # Initialize with saved directory or current directory
        initial_dir = self.gui_main.current_save_directory_path or os.path.dirname(self.ea_image.f_path)
        self.dir_var = tk.StringVar(value=initial_dir)

        self.dir_entry = tk.Entry(
            self.dir_frame,
            textvariable=self.dir_var,
            state="readonly",
            font=("Segoe UI", 8),
        )
        self.dir_entry.place(x=5, y=5, width=430, height=25)

        self.browse_btn = tk.Button(
            self.dir_frame,
            text="Browse...",
            command=self._browse_directory,
            font=("Segoe UI", 9),
        )
        self.browse_btn.place(x=440, y=5, width=80, height=25)

    def _create_progress_frame(self) -> None:
        """Create progress display (initially hidden)."""
        self.progress_frame = tk.LabelFrame(
            self.main_frame, text="Progress", bg="#f0f0f0", padx=5, pady=5
        )
        # Not placed initially - shown when export starts

        self.status_label = tk.Label(
            self.progress_frame,
            text="Ready to export...",
            bg="#f0f0f0",
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.status_label.place(x=5, y=2, width=510, height=20)

        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            orient="horizontal",
            mode="determinate",
        )
        self.progress_bar.place(x=5, y=25, width=510, height=20)

        # Scrollable log text
        self.log_text = tk.Text(
            self.progress_frame,
            height=10,
            state="disabled",
            font=("Consolas", 8),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            wrap="word",
        )
        log_scrollbar = ttk.Scrollbar(self.progress_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        self.log_text.place(x=5, y=50, width=495, height=180)
        log_scrollbar.place(x=500, y=50, width=15, height=180)

        # Configure text tags for colored output
        self.log_text.tag_configure("ok", foreground="#4ec9b0")
        self.log_text.tag_configure("skipped", foreground="#dcdcaa")
        self.log_text.tag_configure("failed", foreground="#f44747")
        self.log_text.tag_configure("info", foreground="#9cdcfe")
        self.log_text.tag_configure("summary", foreground="#ce9178")

    def _create_button_frame(self) -> None:
        """Create action buttons."""
        self.button_frame = tk.Frame(self.main_frame, bg="#f0f0f0")
        self.button_frame.place(x=10, y=480, width=530, height=35)

        self.export_btn = tk.Button(
            self.button_frame,
            text="Export",
            command=self._start_export,
            font=("Segoe UI", 9, "bold"),
            bg="#4CAF50",
            fg="white",
        )
        self.export_btn.place(x=0, y=0, width=120, height=30)

        self.cancel_btn = tk.Button(
            self.button_frame,
            text="Cancel",
            command=self._cancel_export,
            font=("Segoe UI", 9),
            state="disabled",
        )
        self.cancel_btn.place(x=130, y=0, width=120, height=30)

        self.close_btn = tk.Button(
            self.button_frame,
            text="Close",
            command=self._close_dialog,
            font=("Segoe UI", 9),
        )
        self.close_btn.place(x=410, y=0, width=120, height=30)

    def _browse_directory(self) -> None:
        """Open directory picker dialog."""
        directory = filedialog.askdirectory(
            initialdir=self.dir_var.get() or os.path.dirname(self.ea_image.f_path),
            title="Select Output Directory",
        )
        if directory:
            self.dir_var.set(directory)

    def _start_export(self) -> None:
        """Validate and start the batch export."""
        output_dir = self.dir_var.get()
        if not output_dir:
            messagebox.showwarning("Warning", "Please select an output directory.")
            return

        file_format = self.format_var.get()

        # Save directory to config (following existing pattern)
        self.gui_main.current_save_directory_path = output_dir
        self.gui_main.user_config.set("config", "save_directory_path", output_dir)
        with open(self.gui_main.user_config_file_path, "w") as configfile:
            self.gui_main.user_config.write(configfile)

        # Switch to progress phase
        self._show_progress_phase()

        # Reset state
        self.stop_event.clear()
        self._export_finished = False
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = self.ea_image.num_of_entries

        self._append_log(f"Starting batch export of {self.ea_image.f_name}...", "info")
        self._append_log(f"Format: {file_format.upper()}, Output: {output_dir}", "info")
        self._append_log("-" * 60, "info")

        # Start worker thread
        self.worker = BatchExportWorker(
            self.ea_image,
            output_dir,
            file_format,
            self.msg_queue,
            self.stop_event,
        )
        self.worker.start()

        # Start polling queue
        self._poll_queue()

    def _cancel_export(self) -> None:
        """Signal the worker thread to stop."""
        self.stop_event.set()
        self.cancel_btn.config(state="disabled")
        self.status_label.config(text="Cancelling... (finishing current entry)")
        self._append_log("Cancellation requested by user...", "info")

    def _close_dialog(self) -> None:
        """Close the dialog window."""
        if self.worker is not None and self.worker.is_alive():
            self.stop_event.set()
        try:
            self.batch_window.destroy()
        except Exception:
            pass

    def _show_progress_phase(self) -> None:
        """Show progress frame, disable export button, enable cancel button."""
        # Place progress frame
        self.progress_frame.place(x=10, y=250, width=530, height=225)

        # Update button states
        self.export_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")

    def _poll_queue(self) -> None:
        """Poll the message queue from the GUI thread."""
        try:
            while True:
                msg_type, payload = self.msg_queue.get_nowait()

                if msg_type == MSG_PROGRESS:
                    current = payload["current"]
                    total = payload["total"]
                    entry_tag = payload["entry_tag"]
                    status = payload["status"]
                    detail = payload["detail"]

                    # Update progress bar
                    self.progress_bar["value"] = current
                    self.status_label.config(text=f"Exporting {current}/{total}: {entry_tag}")

                    # Append to log
                    if status == "ok":
                        self._append_log(f"[OK]    {entry_tag} -> {detail}", "ok")
                    elif status == "skipped":
                        self._append_log(f"[SKIP]  {entry_tag} -- {detail}", "skipped")
                    elif status == "failed":
                        self._append_log(f"[FAIL]  {entry_tag} -- {detail}", "failed")

                elif msg_type == MSG_LOG:
                    self._append_log(payload["message"], payload.get("level", "info"))

                elif msg_type == MSG_COMPLETE:
                    self._on_export_complete(payload)
                    return

                elif msg_type == MSG_ERROR:
                    self._on_export_error(payload)
                    return

        except queue.Empty:
            pass

        if not self._export_finished:
            self.batch_window.after(100, self._poll_queue)

    def _append_log(self, line: str, tag: str = "info") -> None:
        """Append a line to the scrollable log text."""
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, line + "\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def _on_export_complete(self, result: BatchExportResult) -> None:
        """Handle export completion."""
        self._export_finished = True
        self.progress_bar["value"] = result.total_entries
        self.cancel_btn.config(state="disabled")

        # Build summary
        self._append_log("-" * 60, "info")
        if result.cancelled:
            self._append_log("CANCELLED by user.", "summary")
        else:
            self._append_log("Export complete.", "summary")

        summary_lines = [
            f"  Exported: {result.exported_count}",
            f"  Skipped:  {result.skipped_count}",
            f"  Failed:   {result.failed_count}",
            f"  Time:     {result.elapsed_seconds:.1f}s",
        ]
        for line in summary_lines:
            self._append_log(line, "summary")

        self.status_label.config(
            text=f"Done: {result.exported_count} exported, {result.skipped_count} skipped, {result.failed_count} failed"
        )

        # Show messagebox summary
        msg = (
            f"Batch export {'cancelled' if result.cancelled else 'complete'}.\n\n"
            f"Exported: {result.exported_count}\n"
            f"Skipped: {result.skipped_count}\n"
            f"Failed: {result.failed_count}\n"
            f"Time: {result.elapsed_seconds:.1f}s"
        )
        if result.failed_count > 0:
            # List failed entries
            failed_items = [item for item in result.items if item.status == "failed"]
            msg += "\n\nFailed entries:\n"
            for item in failed_items[:10]:  # Show up to 10
                msg += f"  - {item.entry_tag}: {item.error_message}\n"
            if len(failed_items) > 10:
                msg += f"  ... and {len(failed_items) - 10} more\n"

        messagebox.showinfo("Batch Export", msg)

    def _on_export_error(self, error_info: dict) -> None:
        """Handle fatal export error."""
        self._export_finished = True
        self.cancel_btn.config(state="disabled")

        self._append_log("-" * 60, "info")
        self._append_log(f"FATAL ERROR: {error_info['message']}", "failed")
        self.status_label.config(text="Export failed with error")

        messagebox.showwarning("Batch Export Error", f"Fatal error during export:\n\n{error_info['message']}")

    def _count_exportable_entries(self) -> tuple:
        """Count total, exportable, and unsupported entries."""
        total = self.ea_image.num_of_entries
        exportable = 0
        unsupported = 0

        if self.export_mode == "images":
            for ea_dir in self.ea_image.dir_entry_list:
                if ea_dir.is_img_convert_supported:
                    exportable += 1
                else:
                    unsupported += 1
        else:
            # Raw mode: all entries with raw_data are exportable
            for ea_dir in self.ea_image.dir_entry_list:
                if ea_dir.raw_data:
                    exportable += 1
                else:
                    unsupported += 1

        return total, exportable, unsupported

"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import os
import tkinter as tk
from tkinter import scrolledtext, ttk
from typing import Optional

from reversebox.common.logger import get_logger

from src.EA_Image.batch_export import (
    EXPORT_FORMAT_BMP,
    EXPORT_FORMAT_DDS,
    EXPORT_FORMAT_PNG,
    EXPORT_FORMAT_RAW,
    BatchExportResult,
)

logger = get_logger(__name__)


def _center_over_parent(window: tk.Toplevel, parent: tk.Misc) -> None:
    """Center a Toplevel window over its parent window."""
    window.update_idletasks()
    try:
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        win_w = window.winfo_width()
        win_h = window.winfo_height()
        pos_x = parent_x + max((parent_w - win_w) // 2, 0)
        pos_y = parent_y + max((parent_h - win_h) // 2, 0)
        window.geometry(f"+{pos_x}+{pos_y}")
    except tk.TclError:
        pass


class BatchExportFormatDialog:
    """Modal dialog letting the user pick the output format for a batch export."""

    def __init__(self, parent: tk.Misc, title: str = "Batch Export"):
        self.result: Optional[str] = None
        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.resizable(False, False)
        self.top.transient(parent)

        self._format_var = tk.StringVar(value=EXPORT_FORMAT_PNG)

        tk.Label(self.top, text="Select export format:", anchor="w").pack(fill="x", padx=14, pady=(14, 6))

        options = [
            ("Image - PNG (.png)", EXPORT_FORMAT_PNG),
            ("Image - DDS (.dds)", EXPORT_FORMAT_DDS),
            ("Image - BMP (.bmp)", EXPORT_FORMAT_BMP),
            ("Raw data (.bin)", EXPORT_FORMAT_RAW),
        ]
        for label, value in options:
            tk.Radiobutton(
                self.top, text=label, variable=self._format_var, value=value, anchor="w"
            ).pack(fill="x", padx=24)

        button_frame = tk.Frame(self.top)
        button_frame.pack(fill="x", padx=14, pady=14)
        tk.Button(button_frame, text="Export", width=10, command=self._on_ok).pack(side="right", padx=(6, 0))
        tk.Button(button_frame, text="Cancel", width=10, command=self._on_cancel).pack(side="right")

        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.top.bind("<Return>", lambda event: self._on_ok())
        self.top.bind("<Escape>", lambda event: self._on_cancel())

        _center_over_parent(self.top, parent)
        self.top.grab_set()
        self.top.wait_window()

    def _on_ok(self) -> None:
        self.result = self._format_var.get()
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.top.destroy()


class BatchExportProgressDialog:
    """
    Non-blocking progress dialog driven manually from the export loop.

    The export loop calls :meth:`update_progress` between entries (which refreshes the widgets
    via ``update``), and polls :meth:`is_cancelled` so the user can stop the run with the Cancel
    button. Call :meth:`close` when the run is finished.
    """

    def __init__(self, parent: tk.Misc, total: int, title: str = "Batch Export"):
        self._cancelled = False
        self._closed = False
        self.total = max(total, 1)

        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.minsize(420, 0)

        self._status_var = tk.StringVar(value=f"Exporting 0 / {total} ...")
        tk.Label(self.top, textvariable=self._status_var, anchor="w").pack(fill="x", padx=14, pady=(14, 6))

        self._progress = ttk.Progressbar(self.top, orient="horizontal", mode="determinate", maximum=self.total)
        self._progress.pack(fill="x", padx=14)

        self._current_var = tk.StringVar(value="")
        tk.Label(self.top, textvariable=self._current_var, anchor="w", fg="#555555").pack(
            fill="x", padx=14, pady=(6, 8)
        )

        button_frame = tk.Frame(self.top)
        button_frame.pack(fill="x", padx=14, pady=(0, 14))
        tk.Button(button_frame, text="Cancel", width=10, command=self._on_cancel).pack(side="right")

        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
        _center_over_parent(self.top, parent)
        self.top.grab_set()
        self.top.update()

    def _on_cancel(self) -> None:
        self._cancelled = True
        self._status_var.set("Cancelling...")
        try:
            self.top.update()
        except tk.TclError:
            self._closed = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def update_progress(self, done: int, total: int, current_name: str) -> None:
        if self._closed:
            return
        try:
            self._progress["value"] = done
            self._status_var.set(f"Exporting {done} / {total} ...")
            self._current_var.set(current_name)
            self.top.update()
        except tk.TclError:
            self._closed = True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.top.grab_release()
            self.top.destroy()
        except tk.TclError:
            pass


class BatchExportResultDialog:
    """Modal dialog showing the summary of a batch export plus the details of skipped/failed entries."""

    def __init__(self, parent: tk.Misc, result: BatchExportResult, report_path: Optional[str] = None):
        self.result = result
        self.out_dir = result.out_dir
        self.top = tk.Toplevel(parent)
        self.top.title("Batch Export - Results")
        self.top.transient(parent)
        self.top.resizable(False, False)

        tk.Label(self.top, text=result.summary_text(), anchor="w", font=("Segoe UI", 10, "bold")).pack(
            fill="x", padx=14, pady=(14, 4)
        )

        if result.has_problems():
            tk.Label(self.top, text="Entries that were skipped or failed:", anchor="w").pack(
                fill="x", padx=14, pady=(4, 2)
            )
            details = scrolledtext.ScrolledText(self.top, width=72, height=12, wrap="word")
            details.pack(fill="both", expand=True, padx=14, pady=(0, 4))
            details.insert(tk.END, self._build_details_text())
            details.config(state="disabled")
            if report_path:
                tk.Label(self.top, text=f"Report saved to: {report_path}", anchor="w", fg="#555555").pack(
                    fill="x", padx=14, pady=(0, 4)
                )
        else:
            tk.Label(self.top, text="All selected images were exported successfully.", anchor="w").pack(
                fill="x", padx=14, pady=(0, 6)
            )

        button_frame = tk.Frame(self.top)
        button_frame.pack(fill="x", padx=14, pady=14)
        tk.Button(button_frame, text="Close", width=10, command=self._on_close).pack(side="right", padx=(6, 0))
        if self.out_dir and hasattr(os, "startfile"):
            tk.Button(button_frame, text="Open Folder", width=12, command=self._open_folder).pack(side="right")

        self.top.protocol("WM_DELETE_WINDOW", self._on_close)
        self.top.bind("<Escape>", lambda event: self._on_close())
        _center_over_parent(self.top, parent)
        self.top.grab_set()
        self.top.wait_window()

    def _build_details_text(self) -> str:
        lines = []
        for entry in self.result.skipped:
            lines.append(f"[SKIPPED] {entry.entry_id} ({entry.name})\n    {entry.reason}")
        for entry in self.result.failed:
            lines.append(f"[FAILED]  {entry.entry_id} ({entry.name})\n    {entry.reason}")
        return "\n".join(lines)

    def _open_folder(self) -> None:
        try:
            os.startfile(self.out_dir)  # type: ignore[attr-defined]  # Windows only
        except Exception as error:
            logger.error(f"Could not open output folder: {error}")

    def _on_close(self) -> None:
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()

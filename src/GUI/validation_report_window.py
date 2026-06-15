"""
Copyright © 2025  Bartłomiej Duda
License: GPL-3.0 License
"""

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import center_tk_window
from reversebox.common.logger import get_logger

from src.EA_Image.container_validation import (
    STATUS_OK,
    STATUS_RECOVERABLE,
    STATUS_SEVERE,
)

logger = get_logger(__name__)

# row colors per status
_STATUS_TAG = {
    STATUS_SEVERE: "severe",
    STATUS_RECOVERABLE: "recoverable",
    STATUS_OK: "ok",
}
_STATUS_COLORS = {
    "severe": {"background": "#f8d7da", "foreground": "#842029"},
    "recoverable": {"background": "#fff3cd", "foreground": "#664d03"},
    "ok": {"background": "#ffffff", "foreground": "#1b1b1b"},
}
_BANNER_COLORS = {
    "ISSUES_FOUND": "#842029",
    STATUS_OK: "#0f5132",
}


class ValidationReportWindow:
    def __init__(self, gui_object, ea_image):
        self.gui_object = gui_object
        self.ea_image = ea_image
        self.report: dict = getattr(ea_image, "validation_report", None) or {}
        self.row_meta: dict = {}

        window_width = 940
        window_height = 580
        self.window = tk.Toplevel(width=window_width, height=window_height)
        self.window.wm_title(f"Container Validation Report - {self.report.get('file', {}).get('name', '')}")
        self.window.minsize(640, 400)

        self.main_frame = tk.Frame(self.window, bg="#f0f0f0")
        self.main_frame.pack(fill="both", expand=True)

        self._build_summary_section()
        self._build_tree_section()
        self._build_detail_section()
        self._build_button_section()
        self._populate_tree()

        self.window.lift()
        self.window.focus_force()
        center_tk_window.center_on_screen(self.window)

    # ------------------------------------------------------------------ #
    #                              layout                                #
    # ------------------------------------------------------------------ #

    def _build_summary_section(self):
        summary_frame = tk.Frame(
            self.main_frame, bg="#f0f0f0", highlightbackground="#a6a6a6", highlightthickness=1
        )
        summary_frame.pack(fill="x", padx=8, pady=(8, 4))

        summary = self.report.get("summary", {})
        overall_status = summary.get("status", STATUS_OK)
        banner_text = "No problems detected" if overall_status == STATUS_OK else "Problems detected"
        banner = tk.Label(
            summary_frame,
            text=f"  {banner_text}  -  {summary.get('severe_count', 0)} severe, "
            f"{summary.get('recoverable_count', 0)} recoverable",
            anchor="w",
            font=("Arial", 11, "bold"),
            fg="#ffffff",
            bg=_BANNER_COLORS.get(overall_status, "#842029"),
        )
        banner.pack(fill="x", padx=4, pady=4)

        info_text = tk.Text(summary_frame, height=7, wrap="word", bg="#f7f7f7", relief="flat")
        info_text.pack(fill="x", padx=4, pady=(0, 4))
        info_text.insert(tk.END, self._build_summary_text())
        info_text.config(state="disabled")

    def _build_tree_section(self):
        tree_frame = tk.Frame(self.main_frame, bg="#f0f0f0")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=4)

        columns = ("type", "dims", "data", "status")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Entry / Attachment")
        self.tree.heading("type", text="Format")
        self.tree.heading("dims", text="Dimensions")
        self.tree.heading("data", text="Data (offset..end / size)")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=230, anchor="w")
        self.tree.column("type", width=210, anchor="w")
        self.tree.column("dims", width=110, anchor="center")
        self.tree.column("data", width=200, anchor="center")
        self.tree.column("status", width=100, anchor="center")

        for tag, colors in _STATUS_COLORS.items():
            self.tree.tag_configure(tag, background=colors["background"], foreground=colors["foreground"])

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def _build_detail_section(self):
        detail_frame = tk.Frame(
            self.main_frame, bg="#f0f0f0", highlightbackground="#a6a6a6", highlightthickness=1
        )
        detail_frame.pack(fill="x", padx=8, pady=4)

        tk.Label(detail_frame, text="Details", anchor="w", bg="#f0f0f0", font=("Arial", 9, "bold")).pack(
            fill="x", padx=4, pady=(2, 0)
        )

        detail_inner = tk.Frame(detail_frame, bg="#f0f0f0")
        detail_inner.pack(fill="x", padx=4, pady=(0, 4))

        detail_scroll = ttk.Scrollbar(detail_inner, orient="vertical")
        self.detail_text = tk.Text(detail_inner, height=8, wrap="word", yscrollcommand=detail_scroll.set)
        detail_scroll.config(command=self.detail_text.yview)
        detail_scroll.pack(side="right", fill="y")
        self.detail_text.pack(side="left", fill="x", expand=True)
        self._set_detail_text("Select an entry or attachment above to see its details.")

    def _build_button_section(self):
        button_frame = tk.Frame(self.main_frame, bg="#f0f0f0")
        button_frame.pack(fill="x", padx=8, pady=(0, 8))

        export_button = tk.Button(button_frame, text="Export to JSON...", command=self._export_json, width=18)
        export_button.pack(side="left")

        close_button = tk.Button(button_frame, text="Close", command=self.window.destroy, width=12)
        close_button.pack(side="right")

    # ------------------------------------------------------------------ #
    #                              content                               #
    # ------------------------------------------------------------------ #

    def _build_summary_text(self) -> str:
        file_info = self.report.get("file", {})
        summary = self.report.get("summary", {})
        categories = summary.get("issues_by_category", {})
        category_str = ", ".join(f"{name}: {count}" for name, count in categories.items()) or "none"

        return (
            f"File: {file_info.get('name', '')}\n"
            f"Path: {file_info.get('path', '')}\n"
            f"Signature: {file_info.get('signature', '')}    "
            f"Format version: {file_info.get('format_version', '-')}    "
            f"Endianness: {file_info.get('endianness', '-')}\n"
            f"Declared size: {file_info.get('declared_total_size', '-')}    "
            f"Actual data size: {file_info.get('actual_data_size', '-')}    "
            f"Compressed on disk: {file_info.get('compressed_on_disk', False)}\n"
            f"Entries: {summary.get('entry_count', 0)} "
            f"(declared {file_info.get('declared_entry_count', '-')})    "
            f"Attachments: {summary.get('attachment_count', 0)}\n"
            f"Issues: {summary.get('issue_count', 0)} "
            f"({summary.get('severe_count', 0)} severe, {summary.get('recoverable_count', 0)} recoverable)\n"
            f"By category: {category_str}"
        )

    def _populate_tree(self):
        for entry in self.report.get("entries", []):
            entry_iid = str(entry.get("id"))
            status = entry.get("status", STATUS_OK)
            self.tree.insert(
                "",
                tk.END,
                iid=entry_iid,
                text=str(entry.get("tag") or entry_iid),
                values=(
                    entry.get("format", ""),
                    self._format_dimensions(entry.get("width"), entry.get("height"), entry.get("bpp")),
                    self._format_data_range(entry.get("data_range", {})),
                    status,
                ),
                tags=(_STATUS_TAG.get(status, "ok"),),
                open=True,
            )
            self.row_meta[entry_iid] = {
                "header": self._entry_header_line(entry),
                "issues": entry.get("issues", []),
            }

            for att in entry.get("attachments", []):
                att_iid = str(att.get("id"))
                att_status = att.get("status", STATUS_OK)
                self.tree.insert(
                    entry_iid,
                    tk.END,
                    iid=att_iid,
                    text=str(att.get("tag") or att_iid),
                    values=(
                        att.get("format", ""),
                        "-",
                        self._format_attachment_data(att),
                        att_status,
                    ),
                    tags=(_STATUS_TAG.get(att_status, "ok"),),
                )
                self.row_meta[att_iid] = {
                    "header": self._attachment_header_line(att),
                    "issues": att.get("issues", []),
                }

    @staticmethod
    def _format_dimensions(width, height, bpp) -> str:
        if width is None or height is None:
            return "-"
        if bpp:
            return f"{width}x{height} @ {bpp}bpp"
        return f"{width}x{height}"

    @staticmethod
    def _format_data_range(data_range: dict) -> str:
        offset = data_range.get("offset")
        size = data_range.get("size")
        end = data_range.get("end")
        if offset is None:
            return "-"
        return f"{offset}..{end} ({size}B)"

    @staticmethod
    def _format_attachment_data(att: dict) -> str:
        offset = att.get("data_offset")
        size = att.get("data_size")
        if offset is None:
            return "-"
        return f"{offset} ({size}B)"

    @staticmethod
    def _entry_header_line(entry: dict) -> str:
        offset_range = entry.get("offset_range", {})
        return (
            f"Entry '{entry.get('tag')}' (id {entry.get('id')})\n"
            f"  Format: {entry.get('format')}\n"
            f"  Offset range: {offset_range.get('start')}..{offset_range.get('end')}\n"
            f"  Compression: {entry.get('compression')}    Status: {entry.get('status')}"
        )

    @staticmethod
    def _attachment_header_line(att: dict) -> str:
        offset_range = att.get("offset_range", {})
        return (
            f"Attachment '{att.get('tag')}' (id {att.get('id')})\n"
            f"  Format: {att.get('format')}\n"
            f"  Offset range: {offset_range.get('start')}..{offset_range.get('end')}    "
            f"Status: {att.get('status')}"
        )

    def _on_tree_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        meta = self.row_meta.get(selection[0])
        if not meta:
            return

        lines = [meta["header"], ""]
        issues = meta["issues"]
        if not issues:
            lines.append("No issues detected for this item.")
        else:
            for issue in issues:
                line = f"[{issue['severity'].upper()}] {issue['category']}: {issue['message']}"
                if issue.get("offset") is not None:
                    line += f"  (offset: {issue['offset']})"
                lines.append(line)
                if issue["severity"] == STATUS_SEVERE.lower() and issue.get("file_path"):
                    lines.append(f"    location: {issue['file_path']}")
        self._set_detail_text("\n".join(lines))

    def _set_detail_text(self, text: str):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, text)
        self.detail_text.config(state="disabled")

    # ------------------------------------------------------------------ #
    #                              export                                #
    # ------------------------------------------------------------------ #

    def _export_json(self):
        file_name = self.report.get("file", {}).get("name", "container")
        initial_dir = getattr(self.gui_object, "current_save_directory_path", "") or ""
        try:
            out_path = filedialog.asksaveasfilename(
                defaultextension=".json",
                initialdir=initial_dir,
                initialfile=f"{file_name}_validation_report.json",
                filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
            )
        except Exception as error:
            logger.error(f"Error while opening save dialog: {error}")
            messagebox.showwarning("Warning", "Failed to open save dialog!")
            return

        if not out_path:
            return  # user cancelled

        try:
            with open(out_path, "w", encoding="utf-8") as out_file:
                json.dump(self.report, out_file, indent=2, ensure_ascii=False)
        except Exception as error:
            logger.error(f"Error while exporting validation report: {error}")
            messagebox.showwarning("Warning", "Failed to export report!")
            return

        self._remember_export_directory(out_path)
        messagebox.showinfo("Info", "Validation report exported successfully!")
        logger.info(f"Validation report exported to {out_path}")

    def _remember_export_directory(self, out_path: str):
        try:
            selected_directory = os.path.dirname(out_path)
            self.gui_object.current_save_directory_path = selected_directory
            self.gui_object.user_config.set("config", "save_directory_path", selected_directory)
            with open(self.gui_object.user_config_file_path, "w") as config_file:
                self.gui_object.user_config.write(config_file)
        except Exception as error:
            logger.error(f"Could not persist export directory: {error}")

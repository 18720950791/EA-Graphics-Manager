"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License

Validation report window for EA Graphics Manager.
Displays container validation results in a dedicated Toplevel window.
"""

import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import center_tk_window
from reversebox.common.logger import get_logger

logger = get_logger(__name__)

REPORT_WINDOW_WIDTH = 620
REPORT_WINDOW_HEIGHT = 500


class ValidationReportWindow:
    def __init__(self, gui_main, report):
        self.gui_main = gui_main
        self.report = report

        self.report_window = tk.Toplevel(width=REPORT_WINDOW_WIDTH, height=REPORT_WINDOW_HEIGHT)
        self.report_window.wm_title("Container Validation Report")
        self.report_window.minsize(REPORT_WINDOW_WIDTH, REPORT_WINDOW_HEIGHT)
        self.report_window.resizable(True, True)
        self.report_window.wm_attributes("-toolwindow", "True")
        self.report_window.attributes("-topmost", "true")

        self.main_frame = tk.Frame(self.report_window, bg="#f0f0f0")
        self.main_frame.place(x=0, y=0, relwidth=1, relheight=1)

        # Notebook with 3 tabs
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.place(x=5, y=5, relwidth=1, relheight=1, width=-10, height=-50)

        self._build_summary_tab()
        self._build_anomalies_tab()
        self._build_entries_tab()

        # Bottom button bar
        self._build_button_bar()

        self.report_window.lift()
        self.report_window.focus_force()
        center_tk_window.center_on_screen(self.report_window)

    # ------------------------------------------------------------------
    # Tab 1: Summary
    # ------------------------------------------------------------------

    def _build_summary_tab(self):
        summary_frame = tk.Frame(self.notebook, bg="#f0f0f0")
        self.notebook.add(summary_frame, text="Summary")

        fs = self.report.file_summary
        if not fs:
            tk.Label(summary_frame, text="No file summary available.").pack(pady=20)
            return

        # Status banner
        status_colors = {
            "ok": ("#2e7d32", "#ffffff"),
            "warning": ("#f57f17", "#000000"),
            "error": ("#c62828", "#ffffff"),
            "critical": ("#b71c1c", "#ffffff"),
        }
        bg, fg = status_colors.get(self.report.overall_status, ("#616161", "#ffffff"))
        status_text = f"Overall Status: {self.report.overall_status.upper()}"

        status_frame = tk.Frame(summary_frame, bg=bg)
        status_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        tk.Label(
            status_frame, text=status_text, font=("Segoe UI", 14, "bold"),
            bg=bg, fg=fg, pady=8,
        ).pack()

        # File info grid
        info_frame = tk.LabelFrame(summary_frame, text="File Information", bg="#f0f0f0")
        info_frame.pack(fill=tk.X, padx=10, pady=5)

        info_fields = [
            ("File Name:", fs.file_name),
            ("File Path:", fs.file_path),
            ("File Size:", f"{fs.file_size:,} bytes"),
            ("Signature:", fs.signature),
            ("Format:", f"{fs.format_type} ({fs.format_version})"),
            ("Endianness:", fs.endianness),
        ]

        for i, (label, value) in enumerate(info_fields):
            tk.Label(info_frame, text=label, font=("Segoe UI", 9, "bold"), bg="#f0f0f0", anchor="w").grid(
                row=i, column=0, padx=(10, 5), pady=2, sticky="w"
            )
            tk.Label(info_frame, text=str(value), font=("Segoe UI", 9), bg="#f0f0f0", anchor="w").grid(
                row=i, column=1, padx=5, pady=2, sticky="w"
            )

        # Statistics grid
        stats_frame = tk.LabelFrame(summary_frame, text="Statistics", bg="#f0f0f0")
        stats_frame.pack(fill=tk.X, padx=10, pady=5)

        stats_fields = [
            ("Total Entries:", str(fs.entry_count)),
            ("Supported Images:", str(fs.supported_count)),
            ("Unsupported Entries:", str(fs.unsupported_count)),
            ("Total Attachments:", str(fs.attachment_total)),
            ("Warnings:", str(fs.anomaly_warning_count)),
            ("Errors:", str(fs.anomaly_error_count)),
        ]

        for i, (label, value) in enumerate(stats_fields):
            row = i // 2
            col = (i % 2) * 2
            tk.Label(stats_frame, text=label, font=("Segoe UI", 9, "bold"), bg="#f0f0f0", anchor="w").grid(
                row=row, column=col, padx=(10, 5), pady=2, sticky="w"
            )
            fg_color = "#c62828" if "Error" in label and int(value) > 0 else (
                "#f57f17" if "Warning" in label and int(value) > 0 else "#000000"
            )
            tk.Label(stats_frame, text=value, font=("Segoe UI", 9), bg="#f0f0f0", fg=fg_color, anchor="w").grid(
                row=row, column=col + 1, padx=5, pady=2, sticky="w"
            )

    # ------------------------------------------------------------------
    # Tab 2: Anomalies
    # ------------------------------------------------------------------

    def _build_anomalies_tab(self):
        anomaly_frame = tk.Frame(self.notebook, bg="#f0f0f0")
        self.notebook.add(anomaly_frame, text=f"Anomalies ({len(self.report.anomalies)})")

        if not self.report.anomalies:
            tk.Label(
                anomaly_frame, text="No anomalies detected. Container appears healthy.",
                font=("Segoe UI", 11), fg="#2e7d32", bg="#f0f0f0",
            ).pack(expand=True)
            return

        # Treeview
        columns = ("severity", "type", "entry", "offset", "message")
        self.anomaly_tree = ttk.Treeview(anomaly_frame, columns=columns, show="headings", selectmode="browse")

        self.anomaly_tree.heading("severity", text="Severity")
        self.anomaly_tree.heading("type", text="Type")
        self.anomaly_tree.heading("entry", text="Entry")
        self.anomaly_tree.heading("offset", text="Offset")
        self.anomaly_tree.heading("message", text="Message")

        self.anomaly_tree.column("severity", width=70, minwidth=60, anchor="center")
        self.anomaly_tree.column("type", width=140, minwidth=100)
        self.anomaly_tree.column("entry", width=80, minwidth=60)
        self.anomaly_tree.column("offset", width=80, minwidth=60, anchor="center")
        self.anomaly_tree.column("message", width=220, minwidth=150)

        # Row color tags
        self.anomaly_tree.tag_configure("info", background="#e3f2fd")
        self.anomaly_tree.tag_configure("warning", background="#fff3e0")
        self.anomaly_tree.tag_configure("error", background="#ffebee")
        self.anomaly_tree.tag_configure("critical", background="#ffcdd2")

        for anomaly in self.report.anomalies:
            offset_str = f"0x{anomaly.file_offset:X}" if anomaly.file_offset >= 0 else "N/A"
            self.anomaly_tree.insert(
                "", tk.END,
                values=(
                    anomaly.severity.upper(),
                    anomaly.anomaly_type,
                    anomaly.entry_tag or "N/A",
                    offset_str,
                    anomaly.message,
                ),
                tags=(anomaly.severity,),
            )

        # Scrollbar
        scrollbar = ttk.Scrollbar(anomaly_frame, orient=tk.VERTICAL, command=self.anomaly_tree.yview)
        self.anomaly_tree.configure(yscrollcommand=scrollbar.set)

        self.anomaly_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

        # Double-click for detail
        self.anomaly_tree.bind("<Double-1>", self._on_anomaly_double_click)

    def _on_anomaly_double_click(self, event):
        selection = self.anomaly_tree.selection()
        if not selection:
            return
        item = selection[0]
        values = self.anomaly_tree.item(item, "values")
        # Find the matching anomaly
        for anomaly in self.report.anomalies:
            if anomaly.entry_tag == values[2] and anomaly.anomaly_type == values[1]:
                detail_text = (
                    f"Severity: {anomaly.severity}\n"
                    f"Type: {anomaly.anomaly_type}\n"
                    f"Entry: {anomaly.entry_tag or 'N/A'}\n"
                    f"Entry ID: {anomaly.entry_id or 'N/A'}\n"
                    f"Offset: {anomaly.file_offset}\n"
                    f"\nMessage:\n{anomaly.message}\n"
                )
                if anomaly.details:
                    detail_text += "\nDetails:\n"
                    for k, v in anomaly.details.items():
                        detail_text += f"  {k}: {v}\n"
                messagebox.showinfo("Anomaly Details", detail_text)
                break

    # ------------------------------------------------------------------
    # Tab 3: Entries
    # ------------------------------------------------------------------

    def _build_entries_tab(self):
        entries_frame = tk.Frame(self.notebook, bg="#f0f0f0")
        self.notebook.add(entries_frame, text=f"Entries ({len(self.report.entry_summaries)})")

        if not self.report.entry_summaries:
            tk.Label(entries_frame, text="No entries found.", bg="#f0f0f0").pack(expand=True)
            return

        # Treeview
        columns = ("tag", "type", "size", "range", "attachments", "status")
        self.entry_tree = ttk.Treeview(entries_frame, columns=columns, show="headings", selectmode="browse")

        self.entry_tree.heading("tag", text="Tag")
        self.entry_tree.heading("type", text="Type")
        self.entry_tree.heading("size", text="Data Size")
        self.entry_tree.heading("range", text="Offset Range")
        self.entry_tree.heading("attachments", text="Attachments")
        self.entry_tree.heading("status", text="Status")

        self.entry_tree.column("tag", width=80, minwidth=60)
        self.entry_tree.column("type", width=140, minwidth=100)
        self.entry_tree.column("size", width=80, minwidth=60, anchor="e")
        self.entry_tree.column("range", width=140, minwidth=100, anchor="center")
        self.entry_tree.column("attachments", width=80, minwidth=60, anchor="center")
        self.entry_tree.column("status", width=70, minwidth=60, anchor="center")

        # Row color tags
        self.entry_tree.tag_configure("ok", background="#e8f5e9")
        self.entry_tree.tag_configure("warning", background="#fff3e0")
        self.entry_tree.tag_configure("error", background="#ffebee")

        for entry in self.report.entry_summaries:
            range_str = f"0x{entry.start_offset:X} - 0x{entry.end_offset:X}"
            self.entry_tree.insert(
                "", tk.END,
                values=(
                    entry.tag,
                    entry.entry_type,
                    f"{entry.data_size:,}",
                    range_str,
                    str(entry.attachment_count),
                    entry.status.upper(),
                ),
                tags=(entry.status,),
            )

        # Scrollbar
        scrollbar = ttk.Scrollbar(entries_frame, orient=tk.VERTICAL, command=self.entry_tree.yview)
        self.entry_tree.configure(yscrollcommand=scrollbar.set)

        self.entry_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

    # ------------------------------------------------------------------
    # Button bar
    # ------------------------------------------------------------------

    def _build_button_bar(self):
        button_frame = tk.Frame(self.main_frame, bg="#f0f0f0")
        button_frame.place(relx=0, rely=1, relwidth=1, height=40, y=-40)

        export_btn = tk.Button(
            button_frame, text="Export JSON", font=("Segoe UI", 9),
            command=self._export_json,
        )
        export_btn.pack(side=tk.LEFT, padx=(10, 5), pady=5)

        copy_btn = tk.Button(
            button_frame, text="Copy to Clipboard", font=("Segoe UI", 9),
            command=self._copy_to_clipboard,
        )
        copy_btn.pack(side=tk.LEFT, padx=5, pady=5)

        close_btn = tk.Button(
            button_frame, text="Close", font=("Segoe UI", 9),
            command=lambda: self.report_window.destroy(),
        )
        close_btn.pack(side=tk.RIGHT, padx=(5, 10), pady=5)

    def _export_json(self):
        try:
            out_file = filedialog.asksaveasfile(
                mode="w",
                defaultextension=".json",
                filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
                initialfile=f"{self.report.file_summary.file_name}_validation_report.json" if self.report.file_summary else "validation_report.json",
            )
            if out_file is None:
                return
            self.report.export_json(out_file.name)
            out_file.close()
            messagebox.showinfo("Info", f"Report exported successfully to:\n{out_file.name}")
        except Exception as error:
            logger.error(f"Failed to export validation report: {error}")
            messagebox.showwarning("Warning", f"Failed to export report: {error}")

    def _copy_to_clipboard(self):
        try:
            json_str = json.dumps(self.report.to_dict(), indent=4, ensure_ascii=False)
            self.report_window.clipboard_clear()
            self.report_window.clipboard_append(json_str)
            messagebox.showinfo("Info", "Report JSON copied to clipboard!")
        except Exception as error:
            logger.error(f"Failed to copy to clipboard: {error}")
            messagebox.showwarning("Warning", f"Failed to copy: {error}")

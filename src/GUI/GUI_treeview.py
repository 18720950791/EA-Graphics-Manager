import tkinter as tk
from tkinter import ttk

from src.GUI.tree_filter import FILTER_TYPE_OPTIONS, TreeFilter
from src.GUI.tree_manager import TreeManager


class GuiTreeView(tk.Frame):
    def __init__(self, parent, gui_main):
        super().__init__(parent)
        style = ttk.Style()
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # get rid of the default treeview border
        style.configure("Treeview", indent=10)

        self.tree_frame = tk.Frame(
            parent,
            bg=parent["bg"],
            highlightbackground="grey",
            highlightthickness=1,
        )  # add custom treeview border
        self.tree_frame.place(x=10, y=5, width=125, height=450)

        # --- filter controls ---
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            self.tree_frame,
            textvariable=self.search_var,
            font=("Segoe UI", 8),
        )
        self.search_entry.place(x=2, y=2, width=119, height=18)
        self.search_entry.insert(0, "Search...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self.search_entry.bind("<KeyRelease>", self._on_search_keyrelease)

        self.type_var = tk.StringVar(value="All Types")
        self.type_combo = ttk.Combobox(
            self.tree_frame,
            textvariable=self.type_var,
            state="readonly",
            font=("Segoe UI", 8),
            values=FILTER_TYPE_OPTIONS,
        )
        self.type_combo.place(x=2, y=22, width=119, height=18)
        self.type_combo.bind("<<ComboboxSelected>>", self._on_type_changed)

        # --- treeview ---
        self.treeview_widget = ttk.Treeview(self.tree_frame, show="tree", selectmode="browse")
        self.tree_man = TreeManager(self.treeview_widget)
        self.tree_filter = TreeFilter(self.treeview_widget)
        self.treeview_widget.place(x=0, y=42, width=123, height=406)

        self.treeview_widget.bind("<Button-1>", gui_main.treeview_widget_select)
        self.treeview_widget.bind("<Button-3>", gui_main.treeview_widget_select)

        # debounce state
        self._filter_after_id = None
        self._gui_main = gui_main

    # ---- event handlers ----

    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "Search...":
            self.search_entry.delete(0, tk.END)

    def _on_search_focus_out(self, event):
        if not self.search_entry.get().strip():
            self.search_entry.delete(0, tk.END)
            self.search_entry.insert(0, "Search...")

    def _on_search_keyrelease(self, event):
        if self._filter_after_id:
            self.tree_frame.after_cancel(self._filter_after_id)
        self._filter_after_id = self.tree_frame.after(200, self._apply_filter)

    def _on_type_changed(self, event):
        self._apply_filter()

    def _apply_filter(self):
        self._filter_after_id = None
        text = self.search_var.get().strip()
        if text == "Search...":
            text = ""
        type_cat = self.type_var.get()
        self.tree_filter.apply_filter(self._gui_main.opened_ea_images, text, type_cat)

    def clear_filter(self):
        """Public method for other components to reset the filter."""
        self.search_var.set("")
        self.search_entry.delete(0, tk.END)
        self.search_entry.insert(0, "Search...")
        self.type_var.set("All Types")
        self.tree_filter.clear_filter(self._gui_main.opened_ea_images)

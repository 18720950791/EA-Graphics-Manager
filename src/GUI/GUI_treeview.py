import tkinter as tk
from tkinter import ttk

from src.GUI.tree_filter import TreeFilter
from src.GUI.tree_manager import TreeManager


class GuiTreeView(tk.Frame):
    def __init__(self, parent, gui_main):
        super().__init__(parent)
        self.gui_main = gui_main
        style = ttk.Style()
        style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # get rid of the default treeview border
        style.configure("Treeview", indent=10)

        # search / type filter bar (placed above the resource tree)
        self.filter_frame = tk.Frame(parent, bg=parent["bg"])
        self.filter_frame.place(x=10, y=10, width=125, height=52)

        self.filter_search_var = tk.StringVar()
        self.filter_type_var = tk.StringVar(value=TreeFilter.ALL_TYPES_LABEL)

        self.filter_search_entry = tk.Entry(self.filter_frame, textvariable=self.filter_search_var)
        self.filter_search_entry.place(x=0, y=0, relwidth=1, height=22)

        self.filter_type_combo = ttk.Combobox(
            self.filter_frame,
            textvariable=self.filter_type_var,
            state="readonly",
            values=[TreeFilter.ALL_TYPES_LABEL],
        )
        self.filter_type_combo.place(x=0, y=26, width=90, height=22)

        self.filter_clear_button = tk.Button(self.filter_frame, text="X", command=self.reset_filter)
        self.filter_clear_button.place(x=92, y=26, width=33, height=22)

        self.tree_frame = tk.Frame(
            parent,
            bg=parent["bg"],
            highlightbackground="grey",
            highlightthickness=1,
        )  # add custom treeview border
        self.tree_frame.place(x=10, y=66, width=125, height=389)

        self.treeview_widget = ttk.Treeview(self.tree_frame, show="tree", selectmode="browse")
        self.tree_man = TreeManager(self.treeview_widget)
        self.tree_filter = TreeFilter(self.treeview_widget, gui_main)
        self.treeview_widget.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.treeview_widget.bind("<Button-1>", gui_main.treeview_widget_select)
        self.treeview_widget.bind("<Button-3>", gui_main.treeview_widget_select)

        # react to filter changes
        self.filter_search_var.trace_add("write", self._on_filter_change)
        self.filter_type_combo.bind("<<ComboboxSelected>>", self._on_filter_change)

        self.refresh_filter_options()

    def _on_filter_change(self, *_args):
        self.tree_filter.apply(self.filter_search_var.get(), self.filter_type_var.get())

    def refresh_filter_options(self):
        """Repopulate the type dropdown from the currently loaded containers."""
        type_values = [TreeFilter.ALL_TYPES_LABEL] + self.tree_filter.collect_types()
        self.filter_type_combo["values"] = type_values
        if self.filter_type_var.get() not in type_values:
            self.filter_type_var.set(TreeFilter.ALL_TYPES_LABEL)

    def reset_filter(self):
        """Clear search/type conditions, restoring the original tree view."""
        self.filter_search_var.set("")
        self.filter_type_var.set(TreeFilter.ALL_TYPES_LABEL)
        self.tree_filter.apply("", TreeFilter.ALL_TYPES_LABEL)
        self.tree_filter.reset()

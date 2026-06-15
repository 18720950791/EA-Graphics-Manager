"""
Copyright (c) 2024-2026  Bartlomiej Duda
License: GPL-3.0 License

Tree filter module for EA Graphics Manager.
Provides search and type-based filtering for the resource tree.
"""

import tkinter as tk
from tkinter import ttk

from reversebox.common.logger import get_logger

from src.EA_Image.dir_entry import DirEntry

logger = get_logger(__name__)


# Type category constants
CATEGORY_IMAGE = "Image"
CATEGORY_PALETTE = "Palette"
CATEGORY_COMMENT = "Comment"
CATEGORY_IMGNAME = "Img Name"
CATEGORY_HOTSPOT = "Hot Spot"
CATEGORY_METALBIN = "Metal Bin"
CATEGORY_UNKNOWN = "Unknown"

ALL_TYPES_LABEL = "All Types"

FILTER_TYPE_OPTIONS = [
    ALL_TYPES_LABEL,
    CATEGORY_IMAGE,
    CATEGORY_PALETTE,
    CATEGORY_COMMENT,
    CATEGORY_IMGNAME,
    CATEGORY_HOTSPOT,
    CATEGORY_METALBIN,
    CATEGORY_UNKNOWN,
]

# Record ID sets for categorization
PALETTE_IDS = frozenset({33, 34, 35, 36, 41, 42, 44, 45, 46, 47, 48, 49, 50, 51, 58, 59})

SPECIAL_IDS = {
    105: CATEGORY_METALBIN,
    111: CATEGORY_COMMENT,
    112: CATEGORY_IMGNAME,
    124: CATEGORY_HOTSPOT,
}


def categorize_record_id(record_id) -> str:
    """Map a DirEntry/BinAttachment h_record_id to a broad type category."""
    if record_id is None:
        return CATEGORY_UNKNOWN
    if record_id in SPECIAL_IDS:
        return SPECIAL_IDS[record_id]
    if record_id in PALETTE_IDS:
        return CATEGORY_PALETTE
    if record_id in DirEntry.entry_types:
        return CATEGORY_IMAGE
    return CATEGORY_UNKNOWN


def _text_match(query: str, text: str) -> bool:
    """Case-insensitive substring match. Empty query matches everything."""
    if not query:
        return True
    if text is None:
        return False
    return query.lower() in str(text).lower()


def _type_match(selected_category: str, item_category: str) -> bool:
    """'All Types' matches everything; otherwise exact category match."""
    if selected_category == ALL_TYPES_LABEL:
        return True
    return item_category == selected_category


class TreeFilter:
    """Manages detach/reattach filtering of the resource tree."""

    def __init__(self, tree_widget: ttk.Treeview):
        self.tree_widget = tree_widget
        self._expand_states: dict[str, bool] = {}
        self._selected_iid: str | None = None
        self._is_filtered: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_filter(self, opened_ea_images, text_query: str, type_category: str):
        """Apply search + type filter to the tree.

        Walks the data model (opened_ea_images) to determine which nodes
        match, then detaches all tree items and reattaches only matching
        ones (plus their ancestors). Never modifies the underlying data.
        """
        # Phase 1: save state
        self._save_expand_states()
        self._save_selection()

        # Phase 2: determine matching IIDs from data model
        matching_iids = self._collect_matching_iids(opened_ea_images, text_query, type_category)

        # Phase 3: detach all items (bottom-up)
        self._detach_all()

        # Phase 4: reattach visible items (top-down, data-model order)
        self._reattach_visible(opened_ea_images, matching_iids)

        # Phase 5: restore expand states and selection
        self._restore_expand_states()
        self._restore_selection(matching_iids)

        self._is_filtered = bool(text_query) or type_category != ALL_TYPES_LABEL

    def clear_filter(self, opened_ea_images):
        """Restore the full unfiltered tree in original data-model order."""
        # Phase 1: save state
        self._save_expand_states()
        self._save_selection()

        # Phase 2: detach all
        self._detach_all()

        # Phase 3: reattach ALL items in data-model order
        self._reattach_visible(opened_ea_images, matching_iids=None)

        # Phase 4: restore state
        self._restore_expand_states()
        self._restore_selection(matching_iids=None)

        self._is_filtered = False

    # ------------------------------------------------------------------
    # Phase 2: matching
    # ------------------------------------------------------------------

    def _collect_matching_iids(self, opened_ea_images, text_query: str, type_category: str) -> set[str]:
        """Walk opened_ea_images and collect IIDs that match the filter criteria,
        plus all ancestor IIDs needed to preserve the tree hierarchy."""
        matching_iids: set[str] = set()

        for ea_img in opened_ea_images:
            img_iid = str(ea_img.ea_image_id)
            file_text_match = _text_match(text_query, ea_img.f_name)

            # If the file name matches and no type filter, show everything under it
            if file_text_match and type_category == ALL_TYPES_LABEL:
                matching_iids.add(img_iid)
                for dir_entry in ea_img.dir_entry_list:
                    matching_iids.add(dir_entry.id)
                    for bin_att in dir_entry.bin_attachments_list:
                        matching_iids.add(bin_att.id)
                continue

            # Otherwise evaluate each DirEntry and its BinAttachments
            for dir_entry in ea_img.dir_entry_list:
                dir_name_match = _text_match(text_query, dir_entry.tag)
                dir_type_match = _type_match(type_category, categorize_record_id(dir_entry.h_record_id))
                dir_self_match = dir_name_match and dir_type_match

                # Check BinAttachments first
                for bin_att in dir_entry.bin_attachments_list:
                    att_name_match = _text_match(text_query, bin_att.tag)
                    att_type_match = _type_match(type_category, categorize_record_id(bin_att.h_record_id))
                    if att_name_match and att_type_match:
                        matching_iids.add(bin_att.id)
                        matching_iids.add(dir_entry.id)
                        matching_iids.add(img_iid)

                # DirEntry self-match: show it and all its children
                if dir_self_match:
                    matching_iids.add(dir_entry.id)
                    matching_iids.add(img_iid)
                    for bin_att in dir_entry.bin_attachments_list:
                        matching_iids.add(bin_att.id)

        return matching_iids

    # ------------------------------------------------------------------
    # Phase 3 & 4: detach / reattach
    # ------------------------------------------------------------------

    def _detach_all(self):
        """Detach every item from the tree (bottom-up to avoid ordering issues)."""
        for root_iid in self.tree_widget.get_children(""):
            self._detach_recursive(root_iid)

    def _detach_recursive(self, iid: str):
        """Detach children first, then self."""
        for child in self.tree_widget.get_children(iid):
            self._detach_recursive(child)
        self.tree_widget.detach(iid)

    def _reattach_visible(self, opened_ea_images, matching_iids: set[str] | None):
        """Reattach items in data-model order.

        If matching_iids is None, all items are reattached (used by clear_filter).
        """
        for ea_img in opened_ea_images:
            img_iid = str(ea_img.ea_image_id)
            if matching_iids is not None and img_iid not in matching_iids:
                continue
            self.tree_widget.move(img_iid, "", tk.END)

            for dir_entry in ea_img.dir_entry_list:
                if matching_iids is not None and dir_entry.id not in matching_iids:
                    continue
                self.tree_widget.move(dir_entry.id, img_iid, tk.END)

                for bin_att in dir_entry.bin_attachments_list:
                    if matching_iids is not None and bin_att.id not in matching_iids:
                        continue
                    self.tree_widget.move(bin_att.id, dir_entry.id, tk.END)

    # ------------------------------------------------------------------
    # State save / restore
    # ------------------------------------------------------------------

    def _save_expand_states(self):
        """Walk all currently visible tree items and record their open state."""
        self._expand_states.clear()

        def _walk(iid: str):
            self._expand_states[iid] = self.tree_widget.item(iid, "open")
            for child in self.tree_widget.get_children(iid):
                _walk(child)

        for root_iid in self.tree_widget.get_children(""):
            _walk(root_iid)

    def _restore_expand_states(self):
        """Restore saved open states for items currently in the tree."""
        for iid, is_open in self._expand_states.items():
            try:
                self.tree_widget.item(iid, open=is_open)
            except tk.TclError:
                pass  # item may have been removed (e.g. file closed)

    def _save_selection(self):
        """Record the currently selected tree item."""
        sel = self.tree_widget.selection()
        self._selected_iid = sel[0] if sel else None

    def _restore_selection(self, matching_iids: set[str] | None = None):
        """Re-select the previously selected item if it is still visible."""
        if self._selected_iid:
            if matching_iids is None or self._selected_iid in matching_iids:
                try:
                    self.tree_widget.selection_set(self._selected_iid)
                    self.tree_widget.see(self._selected_iid)
                except tk.TclError:
                    pass

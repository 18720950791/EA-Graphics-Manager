"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License

Resource tree search / type filtering helper.

This module only manipulates the ttk.Treeview *widget* (detach / move /
open state / selection). It never reads or writes the underlying EA image
container objects, so searching can never modify the loaded data.
"""

from reversebox.common.logger import get_logger

logger = get_logger(__name__)


class TreeFilter:
    """Filters a 3-level resource tree (file -> image -> attachment).

    A node stays visible when it is a direct match, when one of its
    ancestors matches (so a matched child keeps its parent hierarchy) or
    when one of its ancestors is a direct match (so a matched node keeps
    its own sub-tree). The original order, expansion state and selection
    are snapshotted when filtering starts and fully restored when the
    conditions are cleared.
    """

    ALL_TYPES_LABEL = "All types"

    def __init__(self, in_widget, gui_main):
        self.tree_widget = in_widget
        self.gui_main = gui_main

        self._active = False  # True while a snapshot is being held
        self._children: dict = {}  # parent_iid -> [child_iid, ...] (original order)
        self._parent: dict = {}  # child_iid -> parent_iid
        self._open: dict = {}  # iid -> original open state (bool)
        self._parents_order: list = []  # nodes in top-down order ("" first)
        self._all_iids: list = []
        self._selection: tuple = ()  # selection captured at snapshot time
        self._type_by_iid: dict = {}  # iid -> entry-type string

    # ------------------------------------------------------------------ #
    #                          type collection                           #
    # ------------------------------------------------------------------ #
    def collect_types(self) -> list:
        """Scan the loaded containers and return the distinct entry types.

        Also (re)builds the iid -> entry-type map used while matching.
        """
        self._type_by_iid = {}
        types: set = set()

        for ea_img in self.gui_main.opened_ea_images:
            for dir_entry in ea_img.dir_entry_list:
                try:
                    entry_type = dir_entry.get_entry_type()
                    self._type_by_iid[dir_entry.id] = entry_type
                    types.add(entry_type)
                except Exception:
                    pass  # entry without a resolvable type is just left unmapped

                for bin_attach in dir_entry.bin_attachments_list:
                    try:
                        attach_type = bin_attach.get_entry_type()
                        self._type_by_iid[bin_attach.id] = attach_type
                        types.add(attach_type)
                    except Exception:
                        pass

        return sorted(types)

    # ------------------------------------------------------------------ #
    #                              snapshot                               #
    # ------------------------------------------------------------------ #
    def _take_snapshot(self) -> None:
        self._children = {}
        self._parent = {}
        self._open = {}

        def walk(node):
            kids = list(self.tree_widget.get_children(node))
            self._children[node] = kids
            for kid in kids:
                self._parent[kid] = node
                self._open[kid] = bool(self.tree_widget.item(kid, "open"))
                walk(kid)

        walk("")
        self._all_iids = list(self._parent.keys())

        # top-down order so a parent is always processed before its children
        order: list = []
        queue: list = [""]
        while queue:
            node = queue.pop(0)
            order.append(node)
            queue.extend(self._children.get(node, []))
        self._parents_order = order

        self._selection = self.tree_widget.selection()
        self._active = True

    def _restore_snapshot(self) -> None:
        # reattach every node in its original position (parents first)
        for parent in self._parents_order:
            for idx, child in enumerate(self._children.get(parent, [])):
                if self.tree_widget.exists(child):
                    self.tree_widget.move(child, parent, idx)

        # restore expansion state
        for iid, is_open in self._open.items():
            if self.tree_widget.exists(iid):
                self.tree_widget.item(iid, open=is_open)

        # restore the original selection if it still exists
        existing = [s for s in self._selection if self.tree_widget.exists(s)]
        if existing:
            self.tree_widget.selection_set(existing)

        self.reset()

    def reset(self) -> None:
        """Forget the current snapshot without touching the widget.

        Used when the tree itself is rebuilt (file opened / closed) so a
        stale snapshot can never be restored.
        """
        self._active = False
        self._children = {}
        self._parent = {}
        self._open = {}
        self._parents_order = []
        self._all_iids = []
        self._selection = ()

    # ------------------------------------------------------------------ #
    #                              matching                              #
    # ------------------------------------------------------------------ #
    def _is_direct_match(self, iid: str, search: str, type_label: str) -> bool:
        text = self.tree_widget.item(iid, "text") or ""
        text_ok = (not search) or (search in text.lower())

        if type_label == self.ALL_TYPES_LABEL:
            type_ok = True
        else:
            type_ok = self._type_by_iid.get(iid) == type_label

        return text_ok and type_ok

    def _compute_keep(self, direct: dict) -> set:
        keep: set = set()

        # the matches themselves + every ancestor (keep parent hierarchy)
        for iid, is_match in direct.items():
            if not is_match:
                continue
            keep.add(iid)
            parent = self._parent.get(iid, "")
            while parent:
                keep.add(parent)
                parent = self._parent.get(parent, "")

        # every descendant of a direct match (keep its sub-tree)
        under_match: dict = {"": False}
        for parent in self._parents_order:
            parent_under = under_match.get(parent, False)
            parent_direct = direct.get(parent, False)
            for child in self._children.get(parent, []):
                child_under = parent_under or parent_direct
                under_match[child] = child_under
                if child_under:
                    keep.add(child)

        return keep

    # ------------------------------------------------------------------ #
    #                            public entry                            #
    # ------------------------------------------------------------------ #
    def apply(self, search_text: str, type_label: str) -> None:
        search = (search_text or "").strip().lower()
        type_label = type_label or self.ALL_TYPES_LABEL
        is_filtering = bool(search) or type_label != self.ALL_TYPES_LABEL

        if not is_filtering:
            if self._active:
                self._restore_snapshot()
            return

        if not self._active:
            self._take_snapshot()

        # best-effort: keep the currently / previously selected item if visible
        current_selection = self.tree_widget.selection()
        if current_selection:
            preferred = current_selection[0]
        elif self._selection:
            preferred = self._selection[0]
        else:
            preferred = None

        direct = {iid: self._is_direct_match(iid, search, type_label) for iid in self._all_iids}
        keep = self._compute_keep(direct)

        # reattach kept nodes in original order (parents before children)
        for parent in self._parents_order:
            if parent != "" and parent not in keep:
                continue
            idx = 0
            for child in self._children.get(parent, []):
                if child in keep:
                    self.tree_widget.move(child, parent, idx)
                    idx += 1

        # hide everything else (a hidden node never has a kept descendant)
        for iid in self._all_iids:
            if iid not in keep:
                self.tree_widget.detach(iid)

        # expand so that the matched nodes are actually revealed
        for parent in self._parents_order:
            if parent == "" or parent not in keep:
                continue
            if any(child in keep for child in self._children.get(parent, [])):
                self.tree_widget.item(parent, open=True)

        # selection preservation
        if preferred is not None and preferred in keep:
            self.tree_widget.selection_set(preferred)
        else:
            current = self.tree_widget.selection()
            if current:
                self.tree_widget.selection_remove(current)

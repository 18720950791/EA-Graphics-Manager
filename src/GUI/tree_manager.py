import tkinter as tk

from reversebox.common.logger import get_logger

logger = get_logger(__name__)


class TreeManager:
    def __init__(self, in_widget):
        self.tree_widget = in_widget

    def add_object(self, in_obj, validation_report=None):
        # Build anomaly lookup by entry_id for fast status checking
        anomaly_status_map = {}
        if validation_report:
            for entry_summary in validation_report.entry_summaries:
                anomaly_status_map[entry_summary.entry_id] = entry_summary.status

        # Configure tag colors for validation status
        self.tree_widget.tag_configure("status_warning", foreground="#e65100")
        self.tree_widget.tag_configure("status_error", foreground="#c62828")

        self.tree_widget.insert(
            "",
            tk.END,
            text=in_obj.f_name,
            iid=in_obj.ea_image_id,
            open=True,
            tags=(in_obj.ea_image_id, "add_object_tag_01"),
        )  # add file to tree, e.g. "awards.ssh"

        # add object children (ea images) to tree
        sub_id = 0
        for dir_entry in in_obj.dir_entry_list:
            sub_id += 1

            # Determine entry tags based on validation status
            entry_status = anomaly_status_map.get(dir_entry.id, "ok")
            if entry_status == "error":
                entry_tags = (dir_entry.id, "add_object_tag_02", "status_error")
            elif entry_status == "warning":
                entry_tags = (dir_entry.id, "add_object_tag_02", "status_warning")
            else:
                entry_tags = (dir_entry.id, "add_object_tag_02")

            self.tree_widget.insert(
                "", tk.END, text=dir_entry.tag, iid=dir_entry.id, open=False, tags=entry_tags
            )
            self.tree_widget.move(dir_entry.id, in_obj.ea_image_id, sub_id)

            # add binary attachments to tree
            bin_att_sub_id = 0
            for bin_att_entry in dir_entry.bin_attachments_list:
                bin_att_sub_id += 1

                # Check if attachment has anomalies
                att_status = "ok"
                if hasattr(bin_att_entry, 'validation_anomalies') and bin_att_entry.validation_anomalies:
                    for a in bin_att_entry.validation_anomalies:
                        if a.severity in ("error", "critical"):
                            att_status = "error"
                            break
                        elif a.severity == "warning":
                            att_status = "warning"

                if att_status == "error":
                    att_tags = (bin_att_entry.id, "add_object_tag_03", "status_error")
                elif att_status == "warning":
                    att_tags = (bin_att_entry.id, "add_object_tag_03", "status_warning")
                else:
                    att_tags = (bin_att_entry.id, "add_object_tag_03")

                self.tree_widget.insert(
                    "",
                    tk.END,
                    text=bin_att_entry.tag,
                    iid=bin_att_entry.id,
                    open=True,
                    tags=att_tags,
                )
                self.tree_widget.move(bin_att_entry.id, dir_entry.id, bin_att_sub_id)

    @staticmethod
    def get_object(in_id, in_ea_images):
        for ea_img in in_ea_images:
            if int(in_id) == int(ea_img.ea_image_id):
                return ea_img

        logger.warning("Warning! Couldn't find matching ea_img object!")
        return None

    @staticmethod
    def get_object_dir(in_ea_img, in_iid):
        for ea_dir in in_ea_img.dir_entry_list:
            if in_iid == ea_dir.id:
                return ea_dir

        logger.warning("Warning! Couldn't find matching DIR object!")
        return None

    @staticmethod
    def get_object_bin_attach(in_dir_entry, in_iid):
        for bin_attach in in_dir_entry.bin_attachments_list:
            if in_iid == bin_attach.id:
                return bin_attach

        logger.warning("Warning! Couldn't find matching BIN_ATTACHMENT object!")
        return None

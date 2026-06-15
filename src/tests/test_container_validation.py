"""
Copyright © 2025  Bartłomiej Duda
License: GPL-3.0 License
"""

import json

from src.EA_Image.attachments.bin_attachment_entry import BinAttachmentEntry
from src.EA_Image.constants import CONVERT_IMAGES_SUPPORTED_TYPES
from src.EA_Image.container_validation import (
    CATEGORY_DECODE_FAILED,
    CATEGORY_ENTRY_COUNT,
    CATEGORY_OUT_OF_BOUNDS,
    CATEGORY_OVERLAP,
    CATEGORY_TRUNCATION,
    CATEGORY_UNKNOWN_ATTACHMENT,
    CATEGORY_UNSUPPORTED_FORMAT,
    SEVERITY_SEVERE,
    STATUS_OK,
    STATUS_RECOVERABLE,
    STATUS_SEVERE,
    validate_ea_image,
)
from src.EA_Image.dir_entry import DirEntry
from src.EA_Image.ea_image_main import EAImage


def _dir_entry(
    entry_id,
    tag,
    *,
    record_id,
    width,
    height,
    bpp,
    start,
    end,
    data_offset,
    data_size,
    header_offset=0,
    header_size=16,
    size_of_block=None,
    compression="NONE",
):
    de = DirEntry(entry_id, tag, start)
    de.end_offset = end
    de.h_record_id = record_id
    de.h_width = width
    de.h_height = height
    de.h_image_bpp = bpp
    de.raw_data_offset = data_offset
    de.raw_data_size = data_size
    de.h_entry_header_offset = header_offset
    de.header_size = header_size
    de.h_size_of_the_block = size_of_block if size_of_block is not None else (end - start)
    de.h_is_image_compressed_masked = compression
    de.h_entry_end_offset = data_offset + data_size
    de.is_img_convert_supported = record_id in CONVERT_IMAGES_SUPPORTED_TYPES
    return de


def _attachment(att_id, *, record_id, start, end, data_offset, data_size, size_of_block=None):
    att = BinAttachmentEntry(att_id, start)
    att.set_tag(record_id)
    att.h_record_id = record_id
    att.start_offset = start
    att.end_offset = end
    att.raw_data_offset = data_offset
    att.raw_data_size = data_size
    att.h_size_of_the_block = size_of_block if size_of_block is not None else (end - start)
    return att


def _ea_image(entries, *, total_f_size, data_len=None, num_of_entries=None, compressed=False):
    ea = EAImage()
    ea.sign = "SHPI"
    ea.format_version = "G354"
    ea.f_name = "test.fsh"
    ea.f_path = "/tmp/test.fsh"
    ea.f_endianess_desc = "little"
    ea.is_total_f_data_compressed = compressed
    ea.total_f_size = total_f_size
    ea.total_f_data = b"\x00" * (data_len if data_len is not None else total_f_size)
    ea.num_of_entries = num_of_entries if num_of_entries is not None else len(entries)
    ea.dir_entry_list = entries
    return ea


def test_clean_container_reports_ok():
    entry = _dir_entry(
        "1_direntry_1", "image1", record_id=5, width=2, height=2, bpp=32, start=0, end=32, data_offset=16, data_size=16
    )
    ea = _ea_image([entry], total_f_size=64)

    report = validate_ea_image(ea)

    assert report["summary"]["status"] == STATUS_OK
    assert report["summary"]["issue_count"] == 0
    assert entry.validation_status == STATUS_OK
    assert entry.validation_issues == []
    # report must be JSON serializable
    json.dumps(report)


def test_detects_overlap_oob_unsupported_truncation_and_attachment():
    unknown_attachment = _attachment(
        "1_direntry_1_binattach_1", record_id=99, start=150, end=250, data_offset=152, data_size=98
    )
    entry_a = _dir_entry(
        "1_direntry_1", "imageA", record_id=5, width=4, height=4, bpp=32, start=0, end=100, data_offset=16, data_size=10
    )
    entry_a.bin_attachments_list = [unknown_attachment]
    entry_b = _dir_entry(
        "1_direntry_2", "imageB", record_id=99, width=8, height=8, bpp=4, start=90, end=300, data_offset=180, data_size=50
    )
    ea = _ea_image([entry_a, entry_b], total_f_size=200)

    report = validate_ea_image(ea)
    categories = report["summary"]["issues_by_category"]

    assert CATEGORY_OVERLAP in categories
    assert CATEGORY_OUT_OF_BOUNDS in categories
    assert CATEGORY_UNSUPPORTED_FORMAT in categories
    assert CATEGORY_TRUNCATION in categories
    assert CATEGORY_UNKNOWN_ATTACHMENT in categories

    assert report["summary"]["status"] == "ISSUES_FOUND"
    assert report["summary"]["severe_count"] >= 1

    # recoverable problems only mark the entry; severe ones drive a severe status
    assert entry_a.validation_status == STATUS_RECOVERABLE
    assert entry_b.validation_status == STATUS_SEVERE
    assert unknown_attachment.validation_status == STATUS_SEVERE

    # severe issues must carry a locatable file position and reason
    for issue in report["issues"]:
        if issue["severity"] == SEVERITY_SEVERE:
            assert issue["file_path"]
            assert issue["offset"] is not None
            assert issue["message"]

    json.dumps(report)


def test_decode_failure_is_recoverable_and_marks_entry():
    entry = _dir_entry(
        "1_direntry_1", "image1", record_id=5, width=2, height=2, bpp=32, start=0, end=32, data_offset=16, data_size=16
    )
    entry.is_img_convert_supported = False
    entry.conversion_error = "boom while decoding"
    ea = _ea_image([entry], total_f_size=64)

    report = validate_ea_image(ea)
    categories = report["summary"]["issues_by_category"]

    assert CATEGORY_DECODE_FAILED in categories
    assert report["summary"]["severe_count"] == 0
    assert entry.validation_status == STATUS_RECOVERABLE


def test_entry_count_mismatch_is_severe_and_locatable():
    entry = _dir_entry(
        "1_direntry_1", "image1", record_id=5, width=2, height=2, bpp=32, start=0, end=32, data_offset=16, data_size=16
    )
    ea = _ea_image([entry], total_f_size=64, num_of_entries=3)

    report = validate_ea_image(ea)
    categories = report["summary"]["issues_by_category"]

    assert CATEGORY_ENTRY_COUNT in categories
    count_issues = [i for i in report["issues"] if i["category"] == CATEGORY_ENTRY_COUNT]
    assert count_issues[0]["severity"] == SEVERITY_SEVERE
    assert count_issues[0]["file_path"]
    assert count_issues[0]["offset"] is not None

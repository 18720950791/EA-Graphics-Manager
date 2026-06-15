"""
Copyright © 2024-2026  Bartłomiej Duda
License: GPL-3.0 License
"""

import os

from src.EA_Image import batch_export as be


class FakeDirEntry:
    """Minimal stand-in for DirEntry exposing only the attributes used by batch export."""

    def __init__(
        self,
        entry_id="1_direntry_1",
        raw_data=b"\x01\x02\x03",
        h_record_id=5,
        is_img_convert_supported=True,
        img_convert_data=b"\x00\x00\x00\x00",
        h_width=1,
        h_height=1,
    ):
        self.id = entry_id
        self.raw_data = raw_data
        self.h_record_id = h_record_id
        self.is_img_convert_supported = is_img_convert_supported
        self.img_convert_data = img_convert_data
        self.h_width = h_width
        self.h_height = h_height


def _make_item(ea_dir, container="awards.ssh", index=1, tag="0000"):
    return be.BatchExportItem(container_name=container, entry_index=index, entry_tag=tag, ea_dir=ea_dir)


def test_sanitize_filename_replaces_invalid_chars():
    assert be.sanitize_filename('a/b\\c:d*e?f"g|h') == "a_b_c_d_e_f_g_h"
    assert be.sanitize_filename("  trailing. ") == "trailing"
    assert be.sanitize_filename("") == ""
    assert be.sanitize_filename(None) == ""


def test_get_extension_for_format():
    assert be.get_extension_for_format(be.EXPORT_FORMAT_PNG) == ".png"
    assert be.get_extension_for_format(be.EXPORT_FORMAT_DDS) == ".dds"
    assert be.get_extension_for_format(be.EXPORT_FORMAT_BMP) == ".bmp"
    assert be.get_extension_for_format(be.EXPORT_FORMAT_RAW) == ".bin"
    assert be.get_extension_for_format("???") == ".bin"


def test_build_unique_filename_avoids_existing_file(tmp_path):
    out_dir = str(tmp_path)
    # pre-create a file that would collide
    with open(os.path.join(out_dir, "img.bin"), "wb") as handle:
        handle.write(b"x")
    used = set()
    name = be.build_unique_filename(out_dir, "img", ".bin", used)
    assert name == "img_001.bin"
    assert "img_001.bin" in used


def test_build_unique_filename_avoids_collision_within_batch(tmp_path):
    out_dir = str(tmp_path)
    used = set()
    first = be.build_unique_filename(out_dir, "img", ".bin", used)
    second = be.build_unique_filename(out_dir, "img", ".bin", used)
    third = be.build_unique_filename(out_dir, "img", ".bin", used)
    assert first == "img.bin"
    assert second == "img_001.bin"
    assert third == "img_002.bin"


def test_build_base_name_is_stable_and_index_based():
    item = _make_item(FakeDirEntry(), container="awards.ssh", index=3, tag="HEAD")
    assert be.build_base_name(item) == "awards_003_HEAD"
    # tag equal to stem is not duplicated
    item2 = _make_item(FakeDirEntry(), container="awards.ssh", index=3, tag="awards")
    assert be.build_base_name(item2) == "awards_003"


def test_is_entry_image_exportable():
    assert be.is_entry_image_exportable(FakeDirEntry(h_record_id=5)) is True
    # unsupported record type
    assert be.is_entry_image_exportable(FakeDirEntry(h_record_id=999)) is False
    # supported type but conversion not performed
    assert be.is_entry_image_exportable(FakeDirEntry(is_img_convert_supported=False)) is False
    # supported type but no converted data
    assert be.is_entry_image_exportable(FakeDirEntry(img_convert_data=None)) is False


def test_run_batch_export_raw_writes_files(tmp_path):
    out_dir = str(tmp_path)
    items = [
        _make_item(FakeDirEntry(entry_id="1_direntry_1", raw_data=b"AAA"), index=1),
        _make_item(FakeDirEntry(entry_id="1_direntry_2", raw_data=b"BBBB"), index=2),
    ]
    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_RAW)
    assert result.exported_count == 2
    assert result.skipped_count == 0
    assert result.failed_count == 0
    assert result.cancelled is False
    written = sorted(os.listdir(out_dir))
    assert written == ["awards_001_0000.bin", "awards_002_0000.bin"]
    with open(os.path.join(out_dir, "awards_001_0000.bin"), "rb") as handle:
        assert handle.read() == b"AAA"


def test_run_batch_export_skips_unsupported_image(tmp_path):
    out_dir = str(tmp_path)
    items = [
        _make_item(FakeDirEntry(entry_id="1_direntry_1", is_img_convert_supported=False), index=1),
        _make_item(FakeDirEntry(entry_id="1_direntry_2", h_record_id=999), index=2),
    ]
    # DDS is an image format -> both entries are not exportable and must be skipped (not failed)
    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_DDS)
    assert result.exported_count == 0
    assert result.skipped_count == 2
    assert result.failed_count == 0
    assert os.listdir(out_dir) == []  # nothing written for skipped entries


def test_run_batch_export_records_failures(tmp_path):
    out_dir = str(tmp_path)
    items = [
        _make_item(FakeDirEntry(entry_id="1_direntry_1", raw_data=b"AAA"), index=1),
        _make_item(FakeDirEntry(entry_id="1_direntry_2", raw_data=b""), index=2),  # empty -> failure
    ]
    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_RAW)
    assert result.exported_count == 1
    assert result.failed_count == 1
    assert result.failed[0].entry_id == "1_direntry_2"
    assert "raw data" in result.failed[0].reason.lower()


def test_run_batch_export_can_be_cancelled(tmp_path):
    out_dir = str(tmp_path)
    items = [
        _make_item(FakeDirEntry(entry_id="1_direntry_1", raw_data=b"AAA"), index=1),
        _make_item(FakeDirEntry(entry_id="1_direntry_2", raw_data=b"BBB"), index=2),
        _make_item(FakeDirEntry(entry_id="1_direntry_3", raw_data=b"CCC"), index=3),
    ]
    calls = {"count": 0}

    def cancel_after_first():
        # False for the first entry, True afterwards
        should_cancel = calls["count"] >= 1
        calls["count"] += 1
        return should_cancel

    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_RAW, cancel_check=cancel_after_first)
    assert result.cancelled is True
    assert result.exported_count == 1
    assert len(os.listdir(out_dir)) == 1


def test_progress_callback_is_called(tmp_path):
    out_dir = str(tmp_path)
    items = [_make_item(FakeDirEntry(entry_id=f"1_direntry_{i}", raw_data=b"D"), index=i) for i in range(1, 4)]
    seen = []
    be.run_batch_export(
        items,
        out_dir,
        be.EXPORT_FORMAT_RAW,
        progress_callback=lambda done, total, name: seen.append((done, total)),
    )
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_report_text_and_file(tmp_path):
    out_dir = str(tmp_path)
    items = [
        _make_item(FakeDirEntry(entry_id="1_direntry_1", raw_data=b""), index=1),  # failure
        _make_item(FakeDirEntry(entry_id="1_direntry_2", is_img_convert_supported=False), index=2),
    ]
    # mix a failure (raw empty) and a skip; use DDS so the unsupported one is skipped
    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_DDS)
    text = result.report_text()
    assert "Skipped entries:" in text
    assert "1_direntry_2" in text
    report_path = be.write_report_file(result, out_dir)
    assert report_path is not None
    assert os.path.exists(report_path)


def test_write_report_file_skipped_when_no_problems(tmp_path):
    out_dir = str(tmp_path)
    items = [_make_item(FakeDirEntry(raw_data=b"AAA"), index=1)]
    result = be.run_batch_export(items, out_dir, be.EXPORT_FORMAT_RAW)
    assert be.write_report_file(result, out_dir) is None

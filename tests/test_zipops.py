"""
Tests for _zipops: low-level zip read/write with metadata preservation.

These tests pin down the contract:
- read_zip_entries: roundtrip-faithful parsing of zip bytes
- write_zip:        preservation of original metadata for unmodified entries
- write_zip:        timestamp of replaced/added entry is set to "now"
- write_zip:        optional reproducible mode (timestamps zeroed)

We build a synthetic minimal .docx in memory as fixture so tests are
hermetic — no binary blobs committed to the repo.
"""

from __future__ import annotations

import io
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker._zipops import (
    ZipEntry,
    read_zip_entries,
    write_zip,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

MINIMAL_DOCX_FILES = {
    "[Content_Types].xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="png" ContentType="image/png"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b'</Types>'
    ),
    "_rels/.rels": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        b'</Relationships>'
    ),
    "word/document.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    ),
    "word/_rels/document.xml.rels": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    ),
    # A tiny valid PNG (1x1 transparent pixel)
    "word/media/image1.png": bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000d49444154789c63000100000005000175e92b730000000049454e44ae426082"
    ),
}

REFERENCE_TIME = (2020, 1, 15, 10, 30, 0)


def make_docx(
    files: dict[str, bytes] | None = None,
    *,
    timestamp: tuple[int, int, int, int, int, int] = REFERENCE_TIME,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    """Build a fake .docx in memory.

    All entries are stamped with the given timestamp so tests can later
    verify which entries kept that timestamp and which got "now".
    """
    if files is None:
        files = MINIMAL_DOCX_FILES

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, data in files.items():
            info = zipfile.ZipInfo(filename=name, date_time=timestamp)
            info.compress_type = compression
            # typical Unix file mode 0644
            info.external_attr = (0o644 & 0xFFFF) << 16
            zf.writestr(info, data)
    return buf.getvalue()


@pytest.fixture
def minimal_docx() -> bytes:
    """A minimal valid .docx with a reference timestamp on all entries."""
    return make_docx()


# ──────────────────────────────────────────────────────────────────────────────
# read_zip_entries
# ──────────────────────────────────────────────────────────────────────────────

class TestReadZipEntries:

    def test_returns_dict_keyed_by_filename(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        assert set(entries.keys()) == set(MINIMAL_DOCX_FILES.keys())

    def test_entry_data_matches_source(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        for name, expected_data in MINIMAL_DOCX_FILES.items():
            assert entries[name].data == expected_data

    def test_entry_info_preserves_timestamp(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        for entry in entries.values():
            assert entry.info.date_time == REFERENCE_TIME

    def test_entry_info_preserves_permissions(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        for entry in entries.values():
            mode = (entry.info.external_attr >> 16) & 0o777
            assert mode == 0o644

    def test_invalid_zip_raises(self):
        with pytest.raises(Exception):  # zipfile.BadZipFile or similar
            read_zip_entries(b"this is not a zip file")

    def test_empty_zip_returns_empty_dict(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        entries = read_zip_entries(buf.getvalue())
        assert entries == {}


# ──────────────────────────────────────────────────────────────────────────────
# write_zip: roundtrip and metadata preservation
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteZipRoundtrip:

    def test_unmodified_roundtrip_preserves_contents(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        rebuilt = write_zip(entries)
        # Re-read and compare
        reread = read_zip_entries(rebuilt)
        assert set(reread.keys()) == set(entries.keys())
        for name in entries:
            assert reread[name].data == entries[name].data

    def test_unmodified_roundtrip_preserves_timestamps(self, minimal_docx):
        # entries we did NOT mark as modified keep
        # their original timestamp.
        entries = read_zip_entries(minimal_docx)
        rebuilt = write_zip(entries)
        reread = read_zip_entries(rebuilt)
        for name in entries:
            assert reread[name].info.date_time == REFERENCE_TIME, (
                f"timestamp changed for {name}"
            )

    def test_unmodified_roundtrip_preserves_permissions(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        rebuilt = write_zip(entries)
        reread = read_zip_entries(rebuilt)
        for name in entries:
            mode = (reread[name].info.external_attr >> 16) & 0o777
            assert mode == 0o644

    def test_preserves_entry_order(self, minimal_docx):
        """Order of entries in the new zip mirrors the order in the input dict."""
        entries = read_zip_entries(minimal_docx)
        rebuilt = write_zip(entries)
        with zipfile.ZipFile(io.BytesIO(rebuilt)) as zf:
            names = zf.namelist()
        assert names == list(entries.keys())


# ──────────────────────────────────────────────────────────────────────────────
# write_zip - modified entries get "now" timestamp
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteZipModifiedTimestamp:

    def test_modified_entry_gets_now_timestamp(self, minimal_docx):
        """When an entry is replaced with new data, its timestamp updates
        to 'now'. Other entries keep their original timestamps."""
        entries = read_zip_entries(minimal_docx)

        # Replace the PNG with new data, marking it modified.
        new_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        before = datetime.now()
        entries["word/media/image1.png"] = ZipEntry.modified(
            filename="word/media/image1.png",
            data=new_png,
            template=entries["word/media/image1.png"],
        )
        rebuilt = write_zip(entries)
        after = datetime.now()

        reread = read_zip_entries(rebuilt)
        # PNG content is the new one
        assert reread["word/media/image1.png"].data == new_png

        # PNG timestamp is "now" (within the test window, with some tolerance
        # for zip's 2-second timestamp resolution and clock skew)
        modified_dt = datetime(*reread["word/media/image1.png"].info.date_time)
        tolerance = timedelta(seconds=5)
        assert (before - tolerance) <= modified_dt <= (after + tolerance), (
            f"modified timestamp {modified_dt} not within expected window"
        )

    def test_other_entries_keep_original_timestamp_when_one_is_modified(self, minimal_docx):
        entries = read_zip_entries(minimal_docx)
        entries["word/media/image1.png"] = ZipEntry.modified(
            filename="word/media/image1.png",
            data=b"new",
            template=entries["word/media/image1.png"],
        )
        rebuilt = write_zip(entries)
        reread = read_zip_entries(rebuilt)
        for name in MINIMAL_DOCX_FILES:
            if name == "word/media/image1.png":
                continue
            assert reread[name].info.date_time == REFERENCE_TIME, (
                f"{name} timestamp should have been preserved"
            )

    def test_modified_entry_inherits_other_metadata_from_template(self, minimal_docx):
        """ZipEntry.modified() takes a `template` entry to inherit perms
        and compression from. Only the timestamp and data change."""
        entries = read_zip_entries(minimal_docx)
        original = entries["word/media/image1.png"]

        entries["word/media/image1.png"] = ZipEntry.modified(
            filename="word/media/image1.png",
            data=b"new content",
            template=original,
        )
        rebuilt = write_zip(entries)
        reread = read_zip_entries(rebuilt)

        # Permissions inherited
        new_mode = (reread["word/media/image1.png"].info.external_attr >> 16) & 0o777
        old_mode = (original.info.external_attr >> 16) & 0o777
        assert new_mode == old_mode

        # Compression inherited
        with zipfile.ZipFile(io.BytesIO(rebuilt)) as zf:
            new_info = zf.getinfo("word/media/image1.png")
        assert new_info.compress_type == original.info.compress_type


# ──────────────────────────────────────────────────────────────────────────────
# write_zip - reproducible mode (optional)
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteZipReproducible:

    def test_reproducible_zeroes_all_timestamps(self, minimal_docx):
        """With reproducible=True, ALL entries get a fixed timestamp,
        including modified ones. This overrides the 'now' default"""
        entries = read_zip_entries(minimal_docx)
        entries["word/media/image1.png"] = ZipEntry.modified(
            filename="word/media/image1.png",
            data=b"new",
            template=entries["word/media/image1.png"],
        )
        rebuilt = write_zip(entries, reproducible=True)

        reread = read_zip_entries(rebuilt)
        # Zip's "zero" date is (1980, 1, 1, 0, 0, 0), the minimum DOS date.
        fixed_date = (1980, 1, 1, 0, 0, 0)
        for entry in reread.values():
            assert entry.info.date_time == fixed_date

    def test_reproducible_two_runs_produce_identical_bytes(self, minimal_docx):
        """Same input + reproducible=True → byte-identical output across runs."""
        entries = read_zip_entries(minimal_docx)
        entries["word/media/image1.png"] = ZipEntry.modified(
            filename="word/media/image1.png",
            data=b"deterministic content",
            template=entries["word/media/image1.png"],
        )
        rebuilt_1 = write_zip(entries, reproducible=True)
        # Sleep to make sure that if timestamps were "now", they'd differ.
        time.sleep(0.05)
        rebuilt_2 = write_zip(entries, reproducible=True)
        assert rebuilt_1 == rebuilt_2


# ──────────────────────────────────────────────────────────────────────────────
# ZipEntry value semantics
# ──────────────────────────────────────────────────────────────────────────────

class TestZipEntry:

    def test_modified_factory_does_not_mutate_template(self, minimal_docx):
        """ZipEntry.modified() must return a NEW entry, not alter the template."""
        entries = read_zip_entries(minimal_docx)
        original = entries["word/media/image1.png"]
        original_data = original.data
        original_timestamp = original.info.date_time

        new_entry = ZipEntry.modified(
            filename="word/media/image1.png",
            data=b"new",
            template=original,
        )

        # Original is unchanged
        assert original.data == original_data
        assert original.info.date_time == original_timestamp
        # New entry has the new data
        assert new_entry.data == b"new"
        # Filename was carried over
        assert new_entry.info.filename == "word/media/image1.png"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

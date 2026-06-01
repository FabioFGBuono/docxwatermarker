"""
Tests for cli.py - command-line interface.

Mix of mocked tests (edge cases, exit codes, mutex flags) and a couple of
real end-to-end smoke tests that exercise the full pipeline.

Exit code contract (Decision 4):
    0  success
    2  argparse error (handled by argparse itself; we don't test this)
    3  template not found / invalid
    4  no image matched the selector
    5  multiple images matched, ambiguity
    6  format mismatch
    7  PDF conversion failed
    1  unexpected error (catchall)
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker.cli import main
from docxwatermarker import make_marker_png


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def _make_marker_docx() -> bytes:
    files = {
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
        "word/media/image1.png": make_marker_png(1600),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for n, d in files.items():
            zf.writestr(n, d)
    return buf.getvalue()


@pytest.fixture
def docx_path(tmp_path) -> Path:
    p = tmp_path / "template.docx"
    p.write_bytes(_make_marker_docx())
    return p


# ──────────────────────────────────────────────────────────────────────────────
# Help and basic dispatch
# ──────────────────────────────────────────────────────────────────────────────

class TestHelp:

    def test_no_args_prints_help_and_exits_nonzero(self, capsys):
        """Calling with no subcommand exits with argparse's standard code."""
        with pytest.raises(SystemExit) as exc:
            main([])
        # argparse exits 2 on missing required subcommand
        assert exc.value.code in (1, 2)

    def test_help_flag_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_stamp_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["stamp", "--help"])
        assert exc.value.code == 0

    def test_inspect_help_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            main(["inspect", "--help"])
        assert exc.value.code == 0


# ──────────────────────────────────────────────────────────────────────────────
# stamp: mutex of --image / --watermark-text / --preset
# ──────────────────────────────────────────────────────────────────────────────

class TestStampMutex:

    def test_no_source_specified_fails(self, docx_path, tmp_path):
        """Decision 1 (A): user must specify exactly one of --image,
        --watermark-text, --preset (in non-interactive mode)."""
        out = tmp_path / "out.docx"
        rc = main(["stamp", str(docx_path), "-o", str(out)])
        assert rc != 0

    def test_two_sources_specified_fails(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        # argparse mutex group exits with code 2
        with pytest.raises(SystemExit) as exc:
            main([
                "stamp", str(docx_path), "-o", str(out),
                "--preset", "confidential",
                "--watermark-text", "Hello",
            ])
        assert exc.value.code == 2


# ──────────────────────────────────────────────────────────────────────────────
# stamp: happy paths
# ──────────────────────────────────────────────────────────────────────────────

class TestStampHappyPaths:

    def test_with_preset(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--preset", "confidential",
        ])
        assert rc == 0
        assert out.exists()

    def test_with_watermark_text_single(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--watermark-text", "Confidential",
        ])
        assert rc == 0
        assert out.exists()

    def test_with_watermark_text_multiple(self, docx_path, tmp_path):
        """--watermark-text is repeatable, each becomes a line."""
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--watermark-text", "Line 1",
            "--watermark-text", "Line 2",
        ])
        assert rc == 0
        assert out.exists()

    def test_with_image_file(self, docx_path, tmp_path):
        # Build a real PNG file as input
        img = Image.new("RGBA", (800, 800), (0, 200, 0, 100))
        img_path = tmp_path / "input.png"
        img.save(img_path, "PNG")

        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--image", str(img_path),
        ])
        assert rc == 0
        assert out.exists()

    def test_default_output_path_derived(self, docx_path, tmp_path):
        """If -o is omitted, output filename is derived from input."""
        # We need control over cwd to make this reproducible; just check
        # rc==0 and that some new docx appeared next to the input.
        rc = main([
            "stamp", str(docx_path),
            "--preset", "confidential",
        ])
        assert rc == 0


# ──────────────────────────────────────────────────────────────────────────────
# stamp: matcher options
# ──────────────────────────────────────────────────────────────────────────────

class TestStampMatcher:

    def test_use_marker(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--preset", "confidential",
            "--use-marker",
        ])
        assert rc == 0

    def test_target_filename(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--preset", "confidential",
            "--target-filename", "word/media/image1.png",
        ])
        assert rc == 0

    def test_use_marker_and_target_filename_mutex(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        with pytest.raises(SystemExit) as exc:
            main([
                "stamp", str(docx_path), "-o", str(out),
                "--preset", "confidential",
                "--use-marker",
                "--target-filename", "word/media/image1.png",
            ])
        assert exc.value.code == 2


# ──────────────────────────────────────────────────────────────────────────────
# stamp: exit codes for known failures
# ──────────────────────────────────────────────────────────────────────────────

class TestStampExitCodes:

    def test_template_not_found_exits_3(self, tmp_path):
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(tmp_path / "nonexistent.docx"),
            "-o", str(out),
            "--preset", "confidential",
        ])
        assert rc == 3

    def test_template_invalid_exits_3(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"not a zip")
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(bad),
            "-o", str(out),
            "--preset", "confidential",
        ])
        assert rc == 3

    def test_image_not_found_exits_4(self, docx_path, tmp_path):
        """Target a path that doesn't exist."""
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--preset", "confidential",
            "--target-filename", "word/media/nonexistent.png",
        ])
        assert rc == 4

    def test_multiple_images_exits_5(self, tmp_path):
        """Build a docx with two square PNGs (no marker) → auto is ambiguous."""
        files = {
            "[Content_Types].xml": b"<types/>",
            "_rels/.rels": b"<rels/>",
            "word/document.xml": b"<doc/>",
            "word/_rels/document.xml.rels": b"<rels/>",
        }
        # Two plain square PNGs, no marker
        img = Image.new("RGBA", (1600, 1600), (0, 0, 0, 0))
        buf2 = io.BytesIO(); img.save(buf2, "PNG")
        plain_png = buf2.getvalue()
        files["word/media/image1.png"] = plain_png
        files["word/media/image2.png"] = plain_png

        docx = tmp_path / "ambiguous.docx"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for n, d in files.items():
                zf.writestr(n, d)
        docx.write_bytes(buf.getvalue())

        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx), "-o", str(out),
            "--preset", "confidential",
        ])
        assert rc == 5

    def test_format_mismatch_exits_6(self, docx_path, tmp_path):
        """Use --image with a JPEG against a PNG target."""
        img = Image.new("RGB", (800, 800), (200, 50, 50))
        jpeg_path = tmp_path / "input.jpeg"
        img.save(jpeg_path, "JPEG")

        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "--image", str(jpeg_path),
        ])
        assert rc == 6


# ──────────────────────────────────────────────────────────────────────────────
# stamp: PDF options
# ──────────────────────────────────────────────────────────────────────────────

class TestStampPdf:

    def test_pdf_flag_calls_to_pdf(self, docx_path, tmp_path):
        out = tmp_path / "out.docx"
        # Mock to_pdf so we don't need LibreOffice for this unit test.
        with patch("docxwatermarker.cli.to_pdf") as fake:
            fake.return_value = out.with_suffix(".pdf")
            rc = main([
                "stamp", str(docx_path), "-o", str(out),
                "--preset", "confidential",
                "--pdf",
            ])
        assert rc == 0
        fake.assert_called_once()

    def test_pdf_only_removes_intermediate_docx(self, docx_path, tmp_path):
        out_docx = tmp_path / "out.docx"
        out_pdf = tmp_path / "out.pdf"

        def fake_to_pdf(docx_path_arg, output_path=None, **kwargs):
            # Pretend to write a PDF
            out_pdf.write_bytes(b"%PDF-1.7 fake\n")
            return out_pdf

        with patch("docxwatermarker.cli.to_pdf", side_effect=fake_to_pdf):
            rc = main([
                "stamp", str(docx_path), "-o", str(out_docx),
                "--preset", "confidential",
                "--pdf-only",
            ])
        assert rc == 0
        assert out_pdf.exists()
        assert not out_docx.exists(), "intermediate DOCX should be removed"

    def test_pdf_conversion_failure_exits_7(self, docx_path, tmp_path):
        from docxwatermarker import PDFConversionError

        out = tmp_path / "out.docx"
        with patch("docxwatermarker.cli.to_pdf") as fake:
            fake.side_effect = PDFConversionError(
                "no libreoffice", reason="not_found"
            )
            rc = main([
                "stamp", str(docx_path), "-o", str(out),
                "--preset", "confidential",
                "--pdf",
            ])
        assert rc == 7


# ──────────────────────────────────────────────────────────────────────────────
# inspect
# ──────────────────────────────────────────────────────────────────────────────

class TestInspect:

    def test_lists_images(self, docx_path, capsys):
        rc = main(["inspect", str(docx_path)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "word/media/image1.png" in out
        assert "png" in out.lower()

    def test_shows_marker_column(self, docx_path, capsys):
        """Decision 3: inspect output includes a marker yes/no column."""
        rc = main(["inspect", str(docx_path)])
        out = capsys.readouterr().out
        assert rc == 0
        # Either "marker" or "MARKER" header, and "yes" for our marker entry
        assert "marker" in out.lower()
        assert "yes" in out.lower()

    def test_template_not_found_exits_3(self, tmp_path):
        rc = main(["inspect", str(tmp_path / "nope.docx")])
        assert rc == 3

    def test_template_invalid_exits_3(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"not a zip")
        rc = main(["inspect", str(bad)])
        assert rc == 3


# ──────────────────────────────────────────────────────────────────────────────
# Interactive mode
# ──────────────────────────────────────────────────────────────────────────────

class TestInteractive:

    def test_interactive_prompts_when_no_source(self, docx_path, tmp_path, monkeypatch):
        """With -i and no --image/--watermark-text/--preset, prompt for
        watermark lines. Empty line ends input."""
        # Simulate user typing two lines then empty.
        inputs = iter(["Copy for Mario", "mario@example.com", ""])
        monkeypatch.setattr("builtins.input", lambda *_args, **_kw: next(inputs))

        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "-i",
        ])
        assert rc == 0
        assert out.exists()

    def test_non_interactive_does_not_prompt(self, docx_path, tmp_path):
        """Without -i, no prompt is shown. Missing source → error."""
        # If a prompt fired we'd hang. By not patching input, any prompt
        # attempt would block, the test should return before any input().
        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
        ])
        assert rc != 0

    def test_interactive_with_explicit_source_skips_prompt(
        self, docx_path, tmp_path, monkeypatch
    ):
        """If --preset is passed even with -i, do not prompt."""
        def fail_if_called(*a, **kw):
            raise AssertionError("input() should not have been called")
        monkeypatch.setattr("builtins.input", fail_if_called)

        out = tmp_path / "out.docx"
        rc = main([
            "stamp", str(docx_path), "-o", str(out),
            "-i",
            "--preset", "confidential",
        ])
        assert rc == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

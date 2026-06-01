"""
End-to-end integration tests for PDF conversion.

These tests SKIP automatically if LibreOffice is not installed. They are
the only way to verify that our subprocess command is actually compatible
with the LibreOffice version installed on the host, mocks can't catch
that drift.

Run with:
    pytest tests/test_pdf_integration.py -v

To run only these (skipping if no LibreOffice):
    pytest tests/test_pdf_integration.py -m requires_libreoffice -v

CI configuration should install LibreOffice (apt-get install libreoffice
on Ubuntu) so these tests run automatically.
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker import PDFConversionError, Template, make_marker_png
from docxwatermarker.pdf import to_pdf, find_libreoffice


# if there is no LibreOffice on PATH, skip every test
# in this file. The marker is also added so CI can target/exclude these.
pytestmark = [
    pytest.mark.requires_libreoffice,
    pytest.mark.skipif(
        find_libreoffice() is None,
        reason="LibreOffice not installed on this system",
    ),
]


def _make_minimal_valid_docx() -> bytes:
    """Build a docx that's complete enough for LibreOffice to open and
    actually convert to PDF. The minimal docx fixtures used elsewhere are
    structurally valid for zip-level operations but not always sufficient
    for LibreOffice's stricter parser."""
    files = {
        "[Content_Types].xml": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
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
            b'<w:body><w:p><w:r><w:t>docxwatermarker integration test document.</w:t></w:r></w:p></w:body>'
            b'</w:document>'
        ),
        "word/_rels/document.xml.rels": (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        ),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestRealConversion:

    def test_basic_conversion_produces_valid_pdf(self, tmp_path):
        docx = tmp_path / "in.docx"
        docx.write_bytes(_make_minimal_valid_docx())
        pdf_path = to_pdf(docx)
        assert pdf_path.exists()
        assert pdf_path.suffix == ".pdf"
        # Quick sanity: PDF files start with "%PDF-"
        with open(pdf_path, "rb") as f:
            head = f.read(5)
        assert head == b"%PDF-", f"output does not look like a PDF: {head!r}"
        assert pdf_path.stat().st_size > 100  # non-trivial size

    def test_explicit_output_path(self, tmp_path):
        docx = tmp_path / "in.docx"
        docx.write_bytes(_make_minimal_valid_docx())
        out = tmp_path / "custom_name.pdf"
        pdf_path = to_pdf(docx, out)
        assert pdf_path == out
        assert out.exists()

    def test_end_to_end_with_template_replace(self, tmp_path):
        """Realistic flow: open template, replace image, save, convert to PDF."""
        # Build a docx with a marker
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
                b'<w:body><w:p><w:r><w:t>Hello.</w:t></w:r></w:p></w:body>'
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
            for name, data in files.items():
                zf.writestr(name, data)

        tmpl = Template.from_bytes(buf.getvalue())

        # Replace with a new PNG (different content, still PNG so no
        # FormatMismatchError).
        from PIL import Image
        new_img = Image.new("RGBA", (1600, 1600), (200, 0, 0, 100))
        replaced = tmpl.replace_image(new_img)

        # Save and convert
        docx_out = tmp_path / "personalized.docx"
        replaced.save(docx_out)
        pdf_out = to_pdf(docx_out)

        assert pdf_out.exists()
        with open(pdf_out, "rb") as f:
            assert f.read(5) == b"%PDF-"

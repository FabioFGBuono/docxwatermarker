"""
Generate a minimal but valid .docx with the docxwatermarker marker embedded as
an image in word/media/. The result is functionally usable as a template.
docxwatermarker can find and replace the marker image. Visually, however, it
won't look like a real document until you open it in Word and arrange the
image as a page-anchored watermark.

Run with:
    python make_sample_template.py

Output:
    sample_template.docx
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from docxwatermarker import make_marker_png


# OOXML skeleton: the minimum set of files Word needs to consider this a
# valid .docx. The XML below intentionally omits any styling, keep it
# minimal so the role of each part is easy to inspect.
_PARTS = {
    "[Content_Types].xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        b'<Default Extension="png" ContentType="image/png"/>'
        b'<Default Extension="xml" ContentType="application/xml"/>'
        b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        b'<Override PartName="/word/document.xml" '
        b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        b'</Types>'
    ),
    "_rels/.rels": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="rId1" '
        b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        b'Target="word/document.xml"/>'
        b'</Relationships>'
    ),
    "word/document.xml": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body>'
        b'<w:p><w:r><w:t>This is the docxwatermarker sample template.</w:t></w:r></w:p>'
        b'<w:p><w:r><w:t>Open it in Word, insert the marker PNG as a page-anchored '
        b'image behind the text, then use docxwatermarker to swap it for a personalized '
        b'watermark.</w:t></w:r></w:p>'
        b'</w:body>'
        b'</w:document>'
    ),
    "word/_rels/document.xml.rels": (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
    ),
}


def main() -> None:
    out_path = Path(__file__).parent / "sample_template.docx"

    # Build the docx in memory, then write it out atomically.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in _PARTS.items():
            zf.writestr(name, data)
        # The marker PNG that docxwatermarker will find and replace. 
        # 1600x1600 is the default size of make_marker_png(), and matches what a
        # full-page watermark expects in a typical Word template.
        zf.writestr("word/media/image1.png", make_marker_png(1600))

    out_path.write_bytes(buf.getvalue())
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print()
    print("Try:")
    print(f"  docxwatermarker inspect {out_path.name}")
    print(f"  docxwatermarker stamp {out_path.name} --preset confidential -o stamped.docx")


if __name__ == "__main__":
    main()

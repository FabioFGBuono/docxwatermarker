"""
03
Use a preset and produce a PDF.

The built-in presets cover the most common document stamps:

    "confidential"  - dark red, "CONFIDENTIAL"
    "draft"         - dark grey, "DRAFT"
    "copy"          - light grey, "COPY"

The PDF step requires LibreOffice ("soffice" or "libreoffice") on PATH,
or DOCXWATERMARKER_SOFFICE pointing to its binary.
"""

from pathlib import Path

from docxwatermarker import Template, make_text_watermark
from docxwatermarker.pdf import to_pdf, find_libreoffice


HERE = Path(__file__).parent
TEMPLATE = HERE / "sample_template.docx"
OUT_DIR = HERE / "_out"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    # Step 1: generate the watermark from a preset.
    watermark = make_text_watermark(preset="confidential")

    # You can mix preset defaults with overridess, e.g. the preset colour
    # and rotation but custom text:
    #   make_text_watermark(["Top Secret"], preset="confidential")

    # Step 2: apply.
    docx_out = OUT_DIR / "03_preset.docx"
    Template.open(TEMPLATE).replace_image(watermark).save(docx_out)
    print(f"wrote {docx_out}")

    # Step 3: PDF, only if LibreOffice is available.
    if find_libreoffice() is None:
        print("LibreOffice not found; skipping PDF generation.")
        print("Install it (or set DOCXWATERMARKER_SOFFICE) to enable PDF output.")
        return

    pdf_out = OUT_DIR / "03_preset.pdf"
    to_pdf(docx_out, pdf_out)
    print(f"wrote {pdf_out}")


if __name__ == "__main__":
    main()

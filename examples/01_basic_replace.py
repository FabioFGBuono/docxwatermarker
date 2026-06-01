"""
01
Basic image replace.

The simplest possible use of docxwatermarker. No text watermark generation, no PDF.

Useful when you've prepared the new image elsewhere (e.g. a logo, a
QR code, an image exported from a design tool).

Prerequisite: run make_sample_template.py first to produce sample_template.docx.
"""

from pathlib import Path

from PIL import Image
from docxwatermarker import Template


HERE = Path(__file__).parent
TEMPLATE = HERE / "sample_template.docx"
OUT_DIR = HERE / "_out"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    # Step 1: build (or load) an image to inject. The sample template's
    # image is a PNG, so we must pass a PNG here too, docxwatermarker refuses
    # to substitute, say, a JPEG for a PNG to keep the package consistent.
    pil_image = Image.new("RGBA", (1600, 1600), (50, 100, 200, 80))
    new_png_path = OUT_DIR / "blue.png"
    pil_image.save(new_png_path, "PNG")

    # Step 2: open the template. docxwatermarker reads it into memory; the
    # file on disk is never touched.
    template = Template.open(TEMPLATE)

    # Step 3: replace the image. By default, ImageMatcher.auto() picks the
    # marker PNG (or the unique square PNG). The returned Template is a
    # new instance — the original `template` is unchanged.
    new_template = template.replace_image(new_png_path)

    # Step 4: write to disk.
    out_path = OUT_DIR / "01_basic_replace.docx"
    new_template.save(out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

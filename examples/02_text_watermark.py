"""
02
Generate a text watermark.

Use make_text_watermark() to produce a diagonal text PNG, then inject it
into the template. The font auto-shrinks to fit, so long lines are safe.
"""

from pathlib import Path

from docxwatermarker import Template, make_text_watermark


HERE = Path(__file__).parent
TEMPLATE = HERE / "sample_template.docx"
OUT_DIR = HERE / "_out"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    # Generate the watermark image. Two lines, default 1600x1600, default
    # rotation 45°, default discreet grey colour. Override any of those
    # with explicit keyword arguments.
    watermark_png = make_text_watermark([
        "Copy for Mario Rossi",
        "mario@example.com",
    ])

    # Single-line use also works, pass a string, not a list:
    #   make_text_watermark("Confidential")

    # Apply.
    out_path = OUT_DIR / "02_text_watermark.docx"
    Template.open(TEMPLATE).replace_image(watermark_png).save(out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

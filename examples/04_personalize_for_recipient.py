"""
04
Personalize a document per recipient.

This is the canonical docxwatermarker use case. The "personalization" 
is just the watermark image, but because it's embedded as a real page-anchored image, 
it survives PDF conversion and shows on every page exactly where you positioned it in Word.

Why this matters... replace_image() returns a NEW Template. The original
is never mutated. That makes the loop below trivially correct, no need
to re-open the template, no risk of leaking state between recipients.
"""

from pathlib import Path

from docxwatermarker import Template, make_text_watermark


HERE = Path(__file__).parent
TEMPLATE = HERE / "sample_template.docx"
OUT_DIR = HERE / "_out"


# A few example recipients. In a real app these come from a database,
# a CRM, a CSV, see 05_batch_csv.py for the CSV variant.
RECIPIENTS = [
    {"name": "Mario Rossi", "email": "mario.rossi@example.com"},
    {"name": "Anna Bianchi", "email": "anna.bianchi@example.com"},
    {"name": "Jean-Luc Petit", "email": "jl@petit.fr"},
]


def slugify(name: str) -> str:
    """Filesystem-safe slug for filenames. Simplified for the example."""
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    # Open the template ONCE outside the loop. Template is immutable, so
    # the same instance is reused safely across iterations.
    template = Template.open(TEMPLATE)

    for r in RECIPIENTS:
        watermark = make_text_watermark([
            f"Copy for {r['name']}",
            r["email"],
        ])
        out_path = OUT_DIR / f"04_for_{slugify(r['name'])}.docx"
        template.replace_image(watermark).save(out_path)
        print(f"  {r['name']:20s} -> {out_path.name}")


if __name__ == "__main__":
    main()

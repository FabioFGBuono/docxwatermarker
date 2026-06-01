"""
05
Batch personalization from a CSV.

The library stays focused on the per-document operation, and batching is
left to the caller. This example shows that "batch" is just a loop over
the API, about 15 lines of glue code. It uses only the standard library
(`csv` module).

CSV format expected:
    name,email
    Mario Rossi,mario@example.com
    Anna Bianchi,anna@example.com
    ...
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

from docxwatermarker import Template, make_text_watermark


HERE = Path(__file__).parent
TEMPLATE = HERE / "sample_template.docx"
OUT_DIR = HERE / "_out"


# Sample CSV produced inline so the example is self-contained. In a real
# project you'd point this at recipients.csv on disk.
SAMPLE_CSV = """name,email
Mario Rossi,mario@example.com
Anna Bianchi,anna@example.com
"""


def slugify(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_")


def stamp_one(template: Template, name: str, email: str, out_dir: Path) -> Path:
    """Stamp a single copy. Returns the output path."""
    watermark = make_text_watermark([f"Copy for {name}", email])
    out_path = out_dir / f"05_for_{slugify(name)}.docx"
    template.replace_image(watermark).save(out_path)
    return out_path


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    template = Template.open(TEMPLATE)
    reader = csv.DictReader(io.StringIO(SAMPLE_CSV))

    produced: list[Path] = []
    errors: list[tuple[str, str]] = []

    for row in reader:
        try:
            path = stamp_one(template, row["name"], row["email"], OUT_DIR)
            produced.append(path)
        except Exception as e:
            # Don't let one bad row abort the whole batch.
            errors.append((row.get("name", "<unknown>"), str(e)))

    print(f"produced {len(produced)} copies:")
    for p in produced:
        print(f"  {p.name}")
    if errors:
        print(f"\n{len(errors)} failures:", file=sys.stderr)
        for name, err in errors:
            print(f"  {name}: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()

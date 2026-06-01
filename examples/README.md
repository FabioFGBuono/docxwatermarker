# Examples

These scripts demonstrate common ways to use `docxwatermarker` from Python and from the command line.

Run them in order from `01_*` to `05_*` for a guided tour, or jump to the one closest to your use case.

## Prerequisites

All examples assume you have a sample template. Generate one with:

```bash
python make_sample_template.py
# creates: sample_template.docx
```

The generated sample template is intentionally minimal, a real Word template with the marker PNG inserted as a page-anchored "behind text" image will look much nicer. See the main README's *"The template-first philosophy"* section for how to prepare one in Word.

## The scripts

| File | What it shows |
|------|---------------|
| `01_basic_replace.py` | Open a template, replace its image with one from disk, save |
| `02_text_watermark.py` | Generate a text watermark and apply it |
| `03_preset_with_pdf.py` | Use a built-in preset (CONFIDENTIAL/DRAFT/COPY) and produce PDF |
| `04_personalize_for_recipient.py` | Personalize one document per recipient with their name/email |
| `05_batch_csv.py` | Run a batch from a CSV of recipients (loop over the API) |

## Running them

```bash
python 01_basic_replace.py
python 02_text_watermark.py
python 03_preset_with_pdf.py
python 04_personalize_for_recipient.py
python 05_batch_csv.py
```

Each script prints what it does and where it writes the output (usually a `_out/` subdirectory next to the script).

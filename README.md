# docxwatermarker

Replace one image inside a `.docx` template, byte for byte, leaving the rest of the file alone.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()
[![Theoretical Computer Science](https://img.shields.io/badge/Theoretical_Computer_Science-%E2%9A%9B%EF%B8%8F-purple)](https://en.wikipedia.org/wiki/Theoretical_computer_science)
[![Automata Theory](https://img.shields.io/badge/Automata_Theory-FA%2C_NFA%2C_PDA-orange)](https://en.wikipedia.org/wiki/Automata_theory)
[![Formal Semantics](https://img.shields.io/badge/Formal_Semantics-%E2%86%92%E2%87%92-darkgreen)](https://en.wikipedia.org/wiki/Formal_semantics_(computer_science))




*[Versione italiana (_italian version_)](README.it.md).* 

## What it is

This repository is an attempt to bridge a gap between teaching and the real world, and at the same time a tool that does real work. Most material on formal specification is either a toy program written to illustrate the method or a heavyweight machine-checked proof of critical code. A readable specification of an ordinary working library, kept honest by an ordinary test rather than a proof assistant, is harder to find. This sits in between.

What you will find here is a small Python library that replaces an image inside a Word document, a complete command-line application that uses it, and two documents that describe the whole in formal terms, an axiomatic specification of the library and an operational semantics of the command-line tool. The documents are tied back to the code by tests, so they cannot drift from it unnoticed, and they are meant in particular for the reader who wants to see working code and a formal specification side by side. A good place to start that side is [`STUDY.pdf`](STUDY.pdf), a short reading path through the code, the specification, and the tests.

## What it does

The library puts a watermark into a `.docx` file by replacing one image inside it.

The library is well-suited to per-recipient document personalization, including confidentiality stamps, draft markers, recipient-specific watermarks for traceability, and branded copies per client.

The package can be used from Python by importing `docxwatermarker`, and `pip install` also puts a `docxwatermarker` command on the path that drives the same library from the shell, so the library can be used without writing Python. The *Quickstart* below shows each.

## When docxwatermarker makes sense

`docxwatermarker` has a narrow scope, and for different use cases other tools serve better.

- **[python-docx](https://python-docx.readthedocs.io)**: programmatic construction or modification of Word documents from scratch. Use it when you don't have a template, or when you need to modify text, tables, headers, or structure.
- **[Aspose.Words](https://products.aspose.com/words/) / [GroupDocs](https://products.groupdocs.com/watermark/)**: commercial, comprehensive document automation including layout-faithful conversion to many formats. Use them when budget allows and you need enterprise-grade features.
- **[pypdf](https://pypdf.readthedocs.io) + [reportlab](https://www.reportlab.com)**: watermark a PDF that already exists. Use them when you're past the Word stage and your input is already a PDF.

`docxwatermarker` sits in the gap between these.

## Quickstart

### Python

```python
from docxwatermarker import Template, make_text_watermark, make_marker_png

# Drop this PNG into your Word template, anchor it to the page.
with open("marker.png", "wb") as f:
    f.write(make_marker_png(1600))

# Personalize and save
watermark = make_text_watermark(["Copy for Mario Rossi", "mario@example.com"])
Template.open("template.docx").replace_image(watermark).save("personalized.docx")
```

### Command line

```bash
docxwatermarker inspect template.docx
docxwatermarker stamp template.docx -o out.docx --preset confidential --pdf
docxwatermarker stamp template.docx -o out.docx \
    --watermark-text "Copy for Mario Rossi" \
    --watermark-text "mario@example.com"
```

## The template-first philosophy

In `docxwatermarker` Word is the source of truth for layout, a common alternative generates watermarks programmatically and ignores the Word layout altogether. Another modifies the document XML, which is fragile and tends to break page anchoring or interact badly with section properties. We chose against both.

The template is set up once in Word.

1. Generate a placeholder PNG with `docxwatermarker`: `python -c "from docxwatermarker import make_marker_png; open('marker.png','wb').write(make_marker_png())"`. The PNG carries an embedded marker so the library can identify it later.
2. In Word, *Insert > Picture > From File* and select `marker.png`.
3. Right-click the image, *Wrap Text > Behind Text*, so the image sits as a watermark layer.
4. *Format Picture > Position > Anchor to Page*, rather than the Word default *Anchor to Paragraph*, which is the reason most watermarks wander between pages.
5. Resize and position the image to cover the area you want watermarked. Save the template.

From that point on, every call to `Template.replace_image()` swaps the image bytes while leaving the anchor, the wrap setting, and the position alone. Every other entry of the document is left untouched, with the same names, contents, and per-entry metadata, so the result opens in Word as if you had replaced the picture by hand. The modified entry is restamped with the current time. The *Reproducible builds* section below covers byte-identical output across runs.

> **Note.** The Word built-in *Watermark* feature (*Design > Watermark*) is convenient but uses a `WordArt` object in the header instead of a page-anchored image, and the result is not always faithful when converted to PDF. `docxwatermarker` works with regular images.

## CLI reference

```
docxwatermarker stamp <template.docx> [options]
docxwatermarker inspect <template.docx>
```

### `stamp`

```
Source (only one required, unless -i is given):
  --image FILE             Use an image file (format must match target's)
  --watermark-text TEXT    Generate a text watermark (repeatable, one per line)
  --preset NAME            Use a built-in preset: confidential | draft | copy

Target selection (default: auto = marker first, then heuristic):
  --use-marker             Target the unique marker PNG
  --target-filename PATH   Target an exact internal path, e.g. word/media/image3.png

Watermark styling (only with --watermark-text / --preset):
  --size N                 Canvas size in pixels (default 1600)
  --rotation DEG           Rotation in degrees (default 45, or preset's value)

Output:
  -o, --output PATH        Output .docx path
  --pdf                    Also produce a PDF next to the DOCX
  --pdf-only               Produce only the PDF (remove the intermediate DOCX)

Modes:
  -i, --interactive        Prompt for watermark lines if no source flag given
  -v, --verbose            INFO-level diagnostic messages
  --debug                  DEBUG-level diagnostics + internal invariant checks
```

### `inspect`

```
PATH                    FORMAT  WIDTHxHEIGHT  SIZE   MARKER
word/media/image1.png   png     1600x1600     10061  yes
word/media/image2.jpeg  jpeg    640x480       5428   no
```

### Exit codes (for scripting)

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Unexpected error (catch-all) |
| 2 | Argument parsing error |
| 3 | Template not found or invalid |
| 4 | No image matched the selector |
| 5 | Multiple images matched (ambiguity) |
| 6 | Replacement image format != target image format |
| 7 | PDF conversion failed |
| 130 | Interrupted (Ctrl-C) |

## Python API

Importing `docxwatermarker` gives access to eighteen names, everything else is internal.

**Core**: `Template`, `ImageMatcher`, `ImageInfo`, `make_marker_png`.

**Watermark generation**: `make_text_watermark`, `WatermarkPreset`, `PRESETS`.

**PDF**: `from docxwatermarker.pdf import to_pdf, find_libreoffice`.

**Debug & diagnostics**: `enable_debug`, `disable_debug`, `is_debug_enabled`, `configure_invariants`, `is_ensure_raising`.

**Exceptions**: `DocxWatermarkerError` (base), `ImageNotFoundError`, `MultipleImagesError`, `FormatMismatchError`, `PDFConversionError`, `InvariantError`. All carry structured `.context` and a JSON-safe `.to_dict()`.

See [`examples/`](examples/) for runnable scripts.

## Examples

| File | What it shows |
|------|---------------|
| [`01_basic_replace.py`](examples/01_basic_replace.py) | Replace an image with one from disk |
| [`02_text_watermark.py`](examples/02_text_watermark.py) | Generate a text watermark and apply it |
| [`03_preset_with_pdf.py`](examples/03_preset_with_pdf.py) | Use a preset and produce a PDF |
| [`04_personalize_for_recipient.py`](examples/04_personalize_for_recipient.py) | One personalized copy per recipient |
| [`05_batch_csv.py`](examples/05_batch_csv.py) | Batch from a CSV (~20 lines on top of the API) |

To get started, `python examples/make_sample_template.py` produces a minimal valid template, and any of the scripts above can then be run against it.

## Design notes & development practices

### No XML manipulation

`docxwatermarker` never reads or writes Word's XML, the `.docx` is a ZIP file, we treat it as such, swap one entry's bytes, and repackage. This is the load-bearing design choice in the library. It is what makes things reliable across Word versions, languages, complex layouts, and OOXML variants, and the price is the requirement of a placeholder image in the template.

### Template is immutable

`Template.replace_image()` returns a new `Template`, and the original is never mutated. This eliminates a class of state bugs that show up in batch loops, and makes chaining safe. The cost is a memory copy of the zip bytes per swap, negligible at typical document sizes.

### Layered architecture, public/internal boundary

The package is laid out so that the public surface stays small and stable while internal helpers can change without breaking callers.

```
docxwatermarker/
├── core.py            ← public: Template, ImageMatcher
├── watermark.py       ← public: make_text_watermark, PRESETS
├── pdf.py             ← public: to_pdf, find_libreoffice
├── errors.py          ← public: exception hierarchy
├── cli.py             ← public: command-line entry point
├── _zipops.py         ← internal: zip read/write with metadata
├── _imagedetect.py    ← internal: image enumeration, marker logic
├── _logging.py        ← internal: logger + debug mode
└── _invariants.py     ← internal: require / ensure
```

Underscored modules sit outside the contractm and anything imported directly from `docxwatermarker`, without further dot-notation, sits inside it.

### Errors carry structured context

Every library exception subclasses `DocxWatermarkerError` and accepts arbitrary keyword arguments stored in `.context`. A typical raise looks like `ImageNotFoundError("...", matcher="auto", candidates=[...])`. The string form prints the context inline for ergonomic debugging, and `.to_dict()` produces a JSON-safe representation, with non-serializable values converted via `repr()` recursively. The same exception object then drives machine-readable logs and human-readable messages.

### Design-by-contract internals

- **`require(condition, message, *, spec=None, **context)`** for preconditions, namely the public-contract checks. It is always active and always raises `InvariantError`.
- **`ensure(condition, message, *, spec=None, **context)`** for postconditions and self-checks. It is active only when debug mode is on. By default it warns and continues, and the behaviour switches to raising via `configure_invariants(raise_on_failure=True)`.

The optional `spec` argument names the clause of the formal specification a check realizes (for example `spec="I2"`). It is the durable link between code and specification, described in the *Axiomatic specification* section below.

The split between `require` and `ensure` reflects who is responsible for the violation. A failed `require` means the caller did something wrong, and fail-fast is the right response. A failed `ensure` means we discovered an internal inconsistency after having produced a correct output, and in production a warning is preferable to a crashed pipeline. In dev and CI, the switch goes the other way. Note that, the `kind` field on `InvariantError` is reserved. And passing `kind=` as a kwarg to `require` or `ensure` raises `TypeError`, so the source of any violation is unambiguous.

### Marker detection via PNG `tEXt`

`make_marker_png()` produces a PNG with a `tEXt` chunk under the standard `Description` key, carrying a long, unique marker string. Detection is a cheap substring search over the early bytes of the file, and the library never instantiates a PNG chunk parser. The choice of the standard `Description` key matters because tools that strip custom PNG metadata typically leave standard keys alone, so the marker survives accidental PNG re-encoding.

### Testing approach

The repository ships over 300 test assertions in `tests/`. Foundation tests pin the public contract of the small primitives (errors, logging, invariants) and run anywhere. Unit tests pin the contract of each module, with heavy use of in-memory fixtures, so that a real `.docx` is built fresh in each test using `zipfile` and no binary blobs are committed to the repo. Integration tests exercise the full pipeline including LibreOffice, are marked with `@pytest.mark.requires_libreoffice`, and skip themselves when LibreOffice is absent.

PDF subprocess interaction is mocked in `test_pdf.py`, which runs anywhere, and exercised for real in `test_pdf_integration.py`, which requires LibreOffice. The mocks pin our wrapper logic, the integration tests catch CLI changes in LibreOffice itself, and both layers are kept for that reason.

`test_spec_crossref.py` keeps the code and the formal specification in agreement. It parses every `spec=` annotation out of the source, checks each against the catalogue in `_invariants.SPEC_REALIZATIONS`, and checks that catalogue against the invariant tables in the specification documents. A clause renamed in one place without the others fails the build.

### Reproducible builds (optional)

The internal `_zipops.write_zip()` accepts a `reproducible=True` flag that zeroes all timestamps to the DOS-minimum (1980-01-01). With this flag two runs over the same input produce byte-identical output. The flag is not yet exposed through `Template.save()`, and will land in v0.2.

### Axiomatic specification (optional reading)

The repository ships a formal specification of the public API in the style of Hoare triples. The English edition is in [`SEMANTICS.pdf`](SEMANTICS.pdf), with LaTeX source in [`SEMANTICS.tex`](SEMANTICS.tex) and a Markdown rendition for in-browser reading in [`SEMANTICS.md`](SEMANTICS.md). The original Italian edition is in [`SEMANTICA.pdf`](SEMANTICA.pdf), [`SEMANTICA.tex`](SEMANTICA.tex), and [`SEMANTICA.md`](SEMANTICA.md).

A library of this scale rarely receives this treatment, the code declares a partial contract through its `require` and `ensure` primitives, in the design-by-contract tradition, and a formal specification closes a loop the code only opens halfway, because every runtime assertion gains a corresponding mathematical statement, and every property in the document should map to a `require` or `ensure` in the code. Code and specification share an identifier, in fact each `require`/`ensure` that realizes a specification clause carries a `spec=` value (such as `spec="I2"`), the same value the specification's invariant table uses. Earlier drafts pointed from the document to the code with line numbers, which go stale as soon as the code moves and give no warning when they do. The `spec=` identifier stays attached to its check wherever the lines fall, and `test_spec_crossref.py` fails the build if code, catalogue, and document fall out of agreement.

### Operational semantics (optional reading)

The axiomatic specification suits the library, whose public operations are pure functions characterized by what they guarantee. The command-line tool is a different kind of object, a process that moves through phases and exits with a code that records where it stopped. That process is modelled in [`OPERATIONAL.pdf`](OPERATIONAL.pdf) (with [`OPERATIONAL.tex`](OPERATIONAL.tex) and [`OPERATIONAL.md`](OPERATIONAL.md), and an Italian edition in [`OPERAZIONALE.pdf`](OPERAZIONALE.pdf), [`OPERAZIONALE.tex`](OPERAZIONALE.tex), [`OPERAZIONALE.md`](OPERAZIONALE.md)) as a transition system in the style of Mancarella's notes, where `stamp` becomes a sequence of configurations and the exit codes are its terminal states. The two documents show the same project under the two semantics, each used where it fits better. The link to the code is checked the same way the axiomatic one is. `test_spec_crossref.py` extracts the exit codes `cmd_stamp` and `cmd_inspect` return and compares them against the codes both operational documents tabulate, so a code cannot drift from its specification unnoticed.

The document is in the tradition of Mancarella's *Note di semantica assiomatica* and Winskel's *Formal Semantics of Programming Languages*.

## Limitations & known issues

- **One image per call.** `Template.replace_image()` swaps one image, the multi-image swap is on the v0.2 roadmap.
- **Format must match.** Replacing a PNG with a JPEG raises `FormatMismatchError`, since the OOXML `[Content_Types].xml` declarations would otherwise drift out of sync. Re-encode the input first if needed.
- **No CSV-batch CLI command** in v0.1. The loop in `examples/05_batch_csv.py` covers the use case in about 20 lines.
- **PDF backend is LibreOffice-only.** Office automation through docx2pdf is not supported in v0.1. PDF conversion failures map to `PDFConversionError` with a specific `reason` field.
- **Marker must be a PNG.** Other formats can still be replaced through `--target-filename` or `ImageMatcher.by_filename()`. The marker mechanism itself relies on a `tEXt` chunk, which is a PNG-only feature.
- **API is alpha.** The shape will change before 1.0. Pin to `~=0.1` if you depend on it.


## Specification Cross-Reference Pattern

The project contains a small hidden gem that might be interesting on its own. It’s a system that links the formal specification to the code in a way that’s independent of physical line numbers and even of refactoring. In traditional formal verification, when you write a specification saying "this invariant is implemented here", so you usually rely on code line numbers, for example, ",invariant I2 is at line 45". The problem is that if you later move that code to line 100 due to refactoring, the reference in the specification becomes wrong. You have to manually update the specification every time the code moves. The solution used here is to rely on an abstract ID instead of a line number. So instead of saying "invariant I3 at line 98", you simply say "invariant I3", and in the code you annotate the relevant function with spec="I3". This way, the link between specification and the code is tied to an ID that stays stable even if the code is moved. But there’s more, the system includes full tracking.system. When the code runs, a function automatically records which specification IDs are actually used. And then with a static catalog listing all expected specifications and their implementations, so you can run a test that automatically checks synchronization and all documented specifications must be implemented, and all implemented specifications must be documented. Instead of manually keeping the mapping between specification and code, you get an automatic system that warns you when something is out of sync. If you add a new specification but forget to document it, the test fails. If you document a specification but don’t implement it, the test fails. It’s an automated quality‑control mechanism for formal verification. It effectively turns all the correctness checks from the formal spec into part of the project’s automated test suite. As far as I know, nobody in the open‑source world had done this before. And in formal proofs, you can use it to logically connect proofs to code through the abstract IDs. Furthermore, if a new developer joins your project, they can simply read the test file or the report generated by the pattern to understand why a particular function performs that specific check, without having to guess.

## License

[MIT](LICENSE).

This is a personal project, written in spare time and released under the MIT license so it can be useful to whoever needs it.

## Acknowledgements

The specification documents lean on the work of others, the axiomatic notation follows Mancarella's lecture notes on axiomatic semantics, the operational one the notes of Barbuti, Mancarella and Turini, both from the University of Pisa, and the treatment rests on the foundational work of Hoare, Dijkstra, Winskel, Meyer, and Plotkin. Thanks are due to their authors for material written to be taught, and freely available, which is what made this case study possible.

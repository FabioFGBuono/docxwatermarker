"""
Command-line interface for docxwatermarker.

Subcommands:
    stamp    Replace an image in a .docx (and optionally produce a PDF).
    inspect  List images inside a .docx, with marker detection.

This module is a thin wrapper over the library API. No business logic
beyond CLI concerns: arg parsing, exit codes, optional interactive prompt.

Exit codes:
    0  success
    1  unexpected / catchall
    2  argparse error (handled by argparse itself)
    3  template not found or invalid
    4  no image matched the selector
    5  multiple images matched, ambiguity
    6  format mismatch between input image and target
    7  PDF conversion failed
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

from docxwatermarker import (
    Template,
    ImageMatcher,
    make_text_watermark,
    PRESETS,
    enable_debug,
)
from docxwatermarker.errors import (
    DocxWatermarkerError,
    ImageNotFoundError,
    MultipleImagesError,
    FormatMismatchError,
    PDFConversionError,
)
from docxwatermarker.pdf import to_pdf
from docxwatermarker._logging import get_logger

_logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docxwatermarker",
        description=(
            "Replace images inside .docx files while preserving "
            "page-anchored layout."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── stamp ────────────────────────────────────────────────────────────
    stamp = subparsers.add_parser(
        "stamp",
        help="Replace an image in a .docx, optionally produce a PDF.",
        description=(
            "Replace the page-anchored image inside a .docx template. "
            "Exactly one of --image, --watermark-text, --preset must be "
            "provided (unless -i / --interactive is used)."
        ),
    )
    stamp.add_argument("template", help="Path to the .docx template")
    stamp.add_argument(
        "-o", "--output",
        help="Output .docx path (default: derived from template name)",
    )

    # Source of the replacement image (mutex)
    src = stamp.add_mutually_exclusive_group()
    src.add_argument(
        "--image",
        help="Use this image file as the watermark "
             "(format must match the target image's format)",
    )
    src.add_argument(
        "--watermark-text",
        action="append",
        metavar="TEXT",
        help="Generate a text watermark. Pass multiple times for multiple lines.",
    )
    src.add_argument(
        "--preset",
        choices=sorted(PRESETS.keys()),
        help="Use a built-in preset watermark.",
    )

    # Target selection (mutex)
    tgt = stamp.add_mutually_exclusive_group()
    tgt.add_argument(
        "--use-marker",
        action="store_true",
        help="Target the unique PNG carrying the docxwatermarker marker "
             "(fails if no marker is present)",
    )
    tgt.add_argument(
        "--target-filename",
        metavar="PATH",
        help="Target an image by its exact internal path "
             "(e.g. word/media/image3.png)",
    )

    # Watermark styling (only relevant with --watermark-text / --preset)
    stamp.add_argument(
        "--size", type=int, default=1600,
        help="Watermark canvas size in pixels (default: 1600)",
    )
    stamp.add_argument(
        "--rotation", type=float, default=None,
        help="Watermark rotation in degrees (default: 45, or preset's value)",
    )

    # PDF output
    pdf = stamp.add_mutually_exclusive_group()
    pdf.add_argument(
        "--pdf", action="store_true",
        help="Also produce a PDF next to the output DOCX",
    )
    pdf.add_argument(
        "--pdf-only", action="store_true",
        help="Produce only the PDF (the intermediate DOCX is removed)",
    )

    # Modes
    stamp.add_argument(
        "-i", "--interactive", action="store_true",
        help="Prompt for watermark lines if no source flag is given",
    )
    stamp.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print INFO-level diagnostic messages",
    )
    stamp.add_argument(
        "--debug", action="store_true",
        help="Print DEBUG-level diagnostics and enable internal invariant checks",
    )

    # ── inspect ──────────────────────────────────────────────────────────
    insp = subparsers.add_parser(
        "inspect",
        help="List images inside a .docx",
        description="Show each image in word/media/ with format, dimensions, "
                    "size, and marker status.",
    )
    insp.add_argument("template", help="Path to the .docx file")
    insp.add_argument(
        "--debug", action="store_true",
        help="Print DEBUG-level diagnostics",
    )

    return parser


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _setup_logging_if_needed(args: argparse.Namespace) -> None:
    if getattr(args, "debug", False):
        enable_debug()
    elif getattr(args, "verbose", False):
        # We don't currently have a separate "verbose" toggle in _logging,
        # so verbose maps to enabling debug-level output without invariant
        # checks. This is a simplification for v0.1.
        enable_debug()


def _collect_lines_interactively() -> list[str]:
    """Read watermark lines from stdin until an empty line."""
    print(
        "Enter the watermark lines. Press Enter on an empty line to finish.",
        file=sys.stderr,
    )
    lines: list[str] = []
    while True:
        try:
            line = input(f"  line {len(lines) + 1}: ")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "":
            break
        lines.append(line)
    return lines


def _derive_output_path(template: Path, suffix: str = ".stamped.docx") -> Path:
    """Default output path: <template_dir>/<stem>.stamped.docx"""
    return template.with_name(template.stem + suffix)


def _build_matcher(args: argparse.Namespace) -> ImageMatcher:
    if args.use_marker:
        return ImageMatcher.by_marker()
    if args.target_filename:
        return ImageMatcher.by_filename(args.target_filename)
    return ImageMatcher.auto()


def _build_replacement_image(args: argparse.Namespace) -> bytes | Path:
    """Return either raw image bytes (for generated watermark) or a Path
    (for an existing image file). Returns whatever Template.replace_image
    can accept directly."""
    if args.image:
        return Path(args.image)
    if args.preset:
        return make_text_watermark(
            preset=args.preset,
            size=args.size,
            rotation=args.rotation,
        )
    # args.watermark_text is a non-empty list at this point
    return make_text_watermark(
        list(args.watermark_text),
        size=args.size,
        rotation=args.rotation,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: stamp
# ──────────────────────────────────────────────────────────────────────────────

def cmd_stamp(args: argparse.Namespace) -> int:
    template_path = Path(args.template)

    # only fires if requested AND no source provided. (Interactive prompt)
    if args.interactive and not (
        args.image or args.watermark_text or args.preset
    ):
        lines = _collect_lines_interactively()
        if not lines:
            print("error: no watermark text entered.", file=sys.stderr)
            return 1
        args.watermark_text = lines

    # Enforce... exactly one source must be set.
    if not (args.image or args.watermark_text or args.preset):
        print(
            "error: must specify one of --image, --watermark-text, --preset "
            "(or use --interactive).",
            file=sys.stderr,
        )
        return 1

    # Resolve output paths.
    if args.output:
        out_docx = Path(args.output)
    else:
        out_docx = _derive_output_path(template_path)

    # Open template.
    try:
        tmpl = Template.open(template_path)
    except FileNotFoundError as e:
        print(f"error: template not found: {template_path}", file=sys.stderr)
        return 3
    except (zipfile.BadZipFile, OSError) as e:
        print(f"error: invalid template file: {e}", file=sys.stderr)
        return 3

    # Build matcher and new image
    matcher = _build_matcher(args)
    try:
        new_image = _build_replacement_image(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Replace.
    try:
        replaced = tmpl.replace_image(new_image, matcher=matcher)
    except ImageNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 4
    except MultipleImagesError as e:
        print(f"error: {e}", file=sys.stderr)
        return 5
    except FormatMismatchError as e:
        print(f"error: {e}", file=sys.stderr)
        return 6
    except FileNotFoundError as e:
        # e.g. --image path does not exist
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Save.
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    replaced.save(out_docx)
    print(f"wrote {out_docx}")

    # PDF generation if requested.
    if args.pdf or args.pdf_only:
        pdf_path = out_docx.with_suffix(".pdf")
        try:
            to_pdf(out_docx, pdf_path)
        except PDFConversionError as e:
            print(f"error: PDF conversion failed: {e}", file=sys.stderr)
            return 7
        print(f"wrote {pdf_path}")

        if args.pdf_only:
            out_docx.unlink(missing_ok=True)
            print(f"removed intermediate {out_docx}")

    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand: inspect
# ──────────────────────────────────────────────────────────────────────────────

def cmd_inspect(args: argparse.Namespace) -> int:
    template_path = Path(args.template)

    try:
        tmpl = Template.open(template_path)
    except FileNotFoundError:
        print(f"error: template not found: {template_path}", file=sys.stderr)
        return 3
    except (zipfile.BadZipFile, OSError) as e:
        print(f"error: invalid template file: {e}", file=sys.stderr)
        return 3

    images = tmpl.list_images()
    if not images:
        print("(no images found under word/media/)")
        return 0

    # Format as a simple aligned table. `is_marker` comes pre-computed
    # on ImageInfo, so we don't need to re-read the zip here.
    header = ("PATH", "FORMAT", "WIDTHxHEIGHT", "SIZE", "MARKER")
    rows = []
    for img in images:
        rows.append((
            img.path,
            img.format,
            f"{img.width}x{img.height}",
            str(img.size_bytes),
            "yes" if img.is_marker else "no",
        ))

    widths = [max(len(r[i]) for r in [header] + rows) for i in range(5)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*header))
    for row in rows:
        print(fmt.format(*row))
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _setup_logging_if_needed(args)

    try:
        if args.command == "stamp":
            return cmd_stamp(args)
        if args.command == "inspect":
            return cmd_inspect(args)
        # argparse 'required=True' makes this unreachable, but be safe.
        parser.print_help(sys.stderr)
        return 2
    except DocxWatermarkerError as e:
        # Catchall for any library error not handled by subcommand-specific
        # exit codes. Should be rare; logs the type so users can report.
        print(f"error ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

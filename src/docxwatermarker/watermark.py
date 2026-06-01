"""
Text watermark PNG generator.

Generates a square PNG with one or more lines of text, optionally rotated,
on a transparent background. The font is auto-sized via binary search to
fit the canvas, so long names/emails shrink rather than clipping.

Convenience presets ("confidential", "draft", "copy") apply a curated
set of defaults: text, color, rotation. Explicit arguments override
preset defaults, so callers can mix and match.

This module's only required dependency is Pillow (already required by
docxwatermarker core).
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Union

from PIL import Image, ImageDraw, ImageFont

from docxwatermarker._logging import get_logger

_logger = get_logger(__name__)


# Path to the font bundled with the package. Used as the last fallback
# before Pillow's bitmap default, so text watermarks remain legible even
# on systems with no installed TTF (minimal containers, Windows Server
# without GUI, etc.). The .ttf file lives inside the package so it ships
# in the wheel.
_BUNDLED_FONT = str(Path(__file__).parent / "_fonts" / "DejaVuSans-Bold.ttf")


# Cross-platform font fallback chain (Decision 4 / Option A).
# Tried in order until one is found. If none exist, we fall back to
# Pillow's bitmap default font (legible but ugly).
_FONT_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:\\Windows\\Fonts\\arialbd.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
)


# ──────────────────────────────────────────────────────────────────────────────
# Presets (Decision 6)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WatermarkPreset:
    """A canned style for make_text_watermark.

    Attributes
    ----------
    lines : tuple of str
        Default text used when the caller doesn't pass `lines` explicitly.
    color : (R, G, B, A) tuple, 0-255
        Default fill color. Alpha controls visibility against the page.
    rotation : float
        Default rotation in degrees, counter-clockwise.
    """
    lines: tuple[str, ...]
    color: tuple[int, int, int, int]
    rotation: float


PRESETS: dict[str, WatermarkPreset] = {
    # Dark red, semi-transparent, the classic legal/security stamp.
    "confidential": WatermarkPreset(
        lines=("CONFIDENTIAL",),
        color=(160, 0, 0, 110),
        rotation=45.0,
    ),
    # Dark grey, neutral "this is a working draft" feel.
    "draft": WatermarkPreset(
        lines=("DRAFT",),
        color=(80, 80, 80, 110),
        rotation=45.0,
    ),
    # Light grey, discrete "this is a copy" marker.
    "copy": WatermarkPreset(
        lines=("COPY",),
        color=(120, 120, 120, 90),
        rotation=45.0,
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_COLOR = (90, 90, 90, 90)


def make_text_watermark(
    lines: Union[str, Sequence[str], None] = None,
    *,
    preset: str | None = None,
    size: int = 1600,
    rotation: float | None = None,
    color: tuple[int, int, int, int] | None = None,
    font_path: str | None = None,
    min_font_size: int = 20,
    max_font_size: int = 180,
    line_spacing: float = 0.25,
) -> bytes:
    """Generate a PNG watermark with centered, optionally-rotated text.

    Parameters
    ----------
    lines
        Text to render. Either a single string (treated as one line) or a
        sequence of strings (one per line). Empty/whitespace-only entries
        are filtered. If at least one preset is given but `lines` is None,
        the preset's default text is used.
    preset
        Name of a WatermarkPreset (see PRESETS). Provides defaults for
        lines/color/rotation; explicit arguments override.
    size
        Canvas side in pixels. Default 1600 (typical Word page-anchored
        watermark template).
    rotation
        Degrees counter-clockwise. Default 45 (or preset's rotation).
    color
        RGBA tuple, 0-255. Default a discreet semi-transparent grey
        (or preset's color).
    font_path
        Path to a TTF/OTF font. None = platform default chain (DejaVu,
        Liberation, Helvetica, Arial), falling back to Pillow's bitmap
        default if none of those exist.
    min_font_size, max_font_size
        Bounds for the auto-sizing binary search. The largest font in
        [min, max] that fits the canvas (at the given rotation) is used.
    line_spacing
        Vertical gap between lines, expressed as a fraction of font_size.
        Default 0.25 (25% of the font size).

    Returns
    -------
    bytes
        PNG-encoded image, transparent background.

    Raises
    ------
    ValueError
        If no usable lines were provided (after filtering) and no preset
        is set; if `preset` names an unknown preset; or if
        min_font_size > max_font_size.
    """
    # Resolve preset (if any) and apply its defaults.
    p: WatermarkPreset | None = None
    if preset is not None:
        if preset not in PRESETS:
            raise ValueError(
                f"Unknown preset {preset!r}. Available: "
                f"{', '.join(sorted(PRESETS))}"
            )
        p = PRESETS[preset]

    # Lines: explicit > preset default > error.
    if lines is None:
        if p is None:
            raise ValueError("either `lines` or `preset` must be provided")
        lines_seq: Sequence[str] = p.lines
    else:
        lines_seq = [lines] if isinstance(lines, str) else lines

    # Filter whitespace-only entries.
    clean_lines = [s for s in lines_seq if s and s.strip()]
    if not clean_lines:
        raise ValueError("no non-empty text lines to render")

    # Color and rotation: explicit > preset > module default.
    if color is None:
        color = p.color if p is not None else _DEFAULT_COLOR
    if rotation is None:
        rotation = p.rotation if p is not None else 45.0

    if min_font_size > max_font_size:
        raise ValueError(
            f"min_font_size ({min_font_size}) > max_font_size ({max_font_size})"
        )

    # Render.
    return _render(
        lines=clean_lines,
        size=size,
        rotation=rotation,
        color=color,
        font_path=font_path,
        min_font_size=min_font_size,
        max_font_size=max_font_size,
        line_spacing=line_spacing,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal rendering
# ──────────────────────────────────────────────────────────────────────────────

# The text box occupies a fraction of the canvas; the rest is margin/rotation
# slack. 0.75 width / 0.55 height matches the geometry needed for diagonal
# text to fit even at 45° without clipping.
_TEXT_BOX_W = 0.75
_TEXT_BOX_H = 0.55


def _render(
    *,
    lines: list[str],
    size: int,
    rotation: float,
    color: tuple[int, int, int, int],
    font_path: str | None,
    min_font_size: int,
    max_font_size: int,
    line_spacing: float,
) -> bytes:
    """Render text lines into a rotated PNG. Pure function: no globals read."""
    box_w = int(size * _TEXT_BOX_W)
    box_h = int(size * _TEXT_BOX_H)

    font_size = _find_max_font_size(
        lines=lines,
        font_path=font_path,
        max_width=box_w,
        max_height=box_h,
        line_spacing=line_spacing,
        lo=min_font_size,
        hi=max_font_size,
    )
    font = _get_font(font_path, font_size)

    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(canvas)

    # Measure all lines once at the chosen font size.
    line_metrics = [_measure(s, font) for s in lines]
    spacing_px = int(font_size * line_spacing)
    total_h = sum(h for _, h in line_metrics) + spacing_px * (len(lines) - 1)
    y = (size - total_h) // 2

    for text, (w, h) in zip(lines, line_metrics):
        x = (size - w) // 2
        draw.text((x, y), text, font=font, fill=color)
        y += h + spacing_px

    if rotation:
        canvas = canvas.rotate(rotation, resample=Image.BILINEAR, expand=False)

    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _find_max_font_size(
    *,
    lines: list[str],
    font_path: str | None,
    max_width: int,
    max_height: int,
    line_spacing: float,
    lo: int,
    hi: int,
) -> int:
    """Binary search for the largest font_size in [lo, hi] such that all
    lines fit within (max_width, max_height) with the given line_spacing.

    Returns lo as a worst-case fallback (never less than the floor).
    """
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _get_font(font_path, mid)
        metrics = [_measure(s, font) for s in lines]
        spacing_px = int(mid * line_spacing)
        total_h = sum(h for _, h in metrics) + spacing_px * (len(lines) - 1)
        max_w = max(w for w, _ in metrics) if metrics else 0
        if max_w <= max_width and total_h <= max_height:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _measure(text: str, font) -> tuple[int, int]:
    """Return (width, height) of `text` rendered with `font`."""
    # Cheap throwaway image just to get a draw context for textbbox.
    img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def _get_font(font_path: str | None, size: int):
    """Load a font at the given size, with fallbacks.

    Resolution order:
        1. font_path argument, if given and the file exists
        2. _FONT_FALLBACKS in order, returning the first that loads
        3. the bundled DejaVu Sans Bold (always present, ships in the wheel)
        4. Pillow's bitmap default font (last-resort, looks ugly)
    """
    candidates: list[str] = []
    if font_path:
        candidates.append(font_path)
    candidates.extend(_FONT_FALLBACKS)
    candidates.append(_BUNDLED_FONT)

    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except (OSError, ValueError) as e:
                _logger.debug("font %r failed to load: %s", path, e)
                continue

    _logger.debug("no TTF found; falling back to Pillow default font")
    return ImageFont.load_default()

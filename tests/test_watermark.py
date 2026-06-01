"""
Tests for watermark.py: text watermark PNG generator.

Pinned contract:

  - make_text_watermark(lines) returns valid PNG bytes
  - Accepts a single string OR a sequence of strings (Decision 3)
  - Default size 1600x1600, customizable via `size`
  - Auto-sizes font between min_font_size and max_font_size to fit canvas
  - Filters empty lines; raises ValueError if no usable text (Decision 5)
  - `preset` argument applies a WatermarkPreset's defaults; explicit args
    override (Decision 6)
  - Unknown preset name raises ValueError with available preset list
  - PRESETS dict exposes three v1 presets: confidential, draft, copy
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker.watermark import (
    make_text_watermark,
    WatermarkPreset,
    PRESETS,
)


# ──────────────────────────────────────────────────────────────────────────────
# Basic output
# ──────────────────────────────────────────────────────────────────────────────

class TestBasicOutput:

    def test_returns_png_bytes(self):
        data = make_text_watermark(["Confidential"])
        assert isinstance(data, bytes)
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_default_size_is_1600(self):
        data = make_text_watermark(["test"])
        img = Image.open(io.BytesIO(data))
        assert img.size == (1600, 1600)

    def test_custom_size_respected(self):
        for sz in (400, 800, 2000):
            data = make_text_watermark(["test"], size=sz)
            img = Image.open(io.BytesIO(data))
            assert img.size == (sz, sz)

    def test_output_is_rgba_with_transparent_background(self):
        """Background must be transparent so the watermark blends with the
        document underneath."""
        data = make_text_watermark(["test"])
        img = Image.open(io.BytesIO(data))
        assert img.mode == "RGBA"
        # Corner pixel must be fully transparent
        corner = img.getpixel((0, 0))
        assert corner[3] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Lines normalization
# ──────────────────────────────────────────────────────────────────────────────

class TestLinesNormalization:

    def test_accepts_string(self):
        a = make_text_watermark("Confidential")
        b = make_text_watermark(["Confidential"])
        # Both produce valid PNGs (exact byte equality not asserted because
        # Pillow encoding may vary; we check structural sameness instead).
        assert a[:8] == b[:8] == b"\x89PNG\r\n\x1a\n"

    def test_accepts_list(self):
        data = make_text_watermark(["line1", "line2"])
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_accepts_tuple(self):
        data = make_text_watermark(("line1", "line2"))
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ──────────────────────────────────────────────────────────────────────────────
# Empty input handling
# ──────────────────────────────────────────────────────────────────────────────

class TestEmptyInput:

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            make_text_watermark([])

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            make_text_watermark("")

    def test_all_empty_lines_raises(self):
        with pytest.raises(ValueError):
            make_text_watermark(["", "", ""])

    def test_whitespace_only_lines_raise(self):
        with pytest.raises(ValueError):
            make_text_watermark(["   ", "\t\n"])

    def test_empty_lines_filtered_keeping_non_empty(self):
        """A mix of empty and non-empty lines: the empties are filtered
        and rendering proceeds with what remains."""
        # If this raised, the implementation would have failed empties
        # incorrectly. We don't compare pixels, just confirm it runs.
        data = make_text_watermark(["", "Real Text", ""])
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ──────────────────────────────────────────────────────────────────────────────
# Auto-sizing
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoSizing:

    def test_short_text_uses_large_font(self):
        """Short text in a big canvas should produce a watermark with a
        font near the maximum. We can't easily inspect the font size from
        the rendered PNG, but we can ensure the rendered area has visible
        pixels in a sensible region of the canvas."""
        data = make_text_watermark(["X"], size=800, max_font_size=200)
        img = Image.open(io.BytesIO(data))
        # Find any non-transparent pixel: there must be some.
        non_transparent = [
            (x, y) for x in range(0, 800, 50) for y in range(0, 800, 50)
            if img.getpixel((x, y))[3] > 0
        ]
        assert len(non_transparent) > 0

    def test_long_text_does_not_overflow(self):
        """A very long single line must still fit in the canvas. We check
        that the rendered text doesn't paint pixels in the extreme corners
        (which would happen if the font wasn't shrunk enough)."""
        very_long = "ThisIsAnExtremelyLongNameOrEmailThatShouldShrinkToFit"
        data = make_text_watermark([very_long], size=800)
        img = Image.open(io.BytesIO(data))
        # Corners must remain transparent (text is rotated 45°, so corners
        # are well away from the text bounding box).
        for x, y in [(0, 0), (799, 0), (0, 799), (799, 799)]:
            assert img.getpixel((x, y))[3] == 0

    def test_min_max_font_constraints_honored(self):
        """min_font_size=max_font_size forces a fixed size"""
        data = make_text_watermark(
            ["test"], size=400, min_font_size=40, max_font_size=40,
        )
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_min_greater_than_max_raises(self):
        with pytest.raises(ValueError):
            make_text_watermark(["x"], min_font_size=100, max_font_size=50)


# ──────────────────────────────────────────────────────────────────────────────
# Color and rotation
# ──────────────────────────────────────────────────────────────────────────────

class TestColorAndRotation:

    def test_custom_color_produces_pixels_of_that_color(self):
        """When we use a fully opaque red, some pixels in the rendered text
        area must be (nearly) pure red."""
        data = make_text_watermark(
            ["HELLO"], size=400, color=(255, 0, 0, 255), rotation=0,
        )
        img = Image.open(io.BytesIO(data))
        # Sample several pixels in the central area
        reds = 0
        for x in range(100, 300, 10):
            for y in range(150, 250, 10):
                r, g, b, a = img.getpixel((x, y))
                if a > 0 and r > 200 and g < 50 and b < 50:
                    reds += 1
        assert reds > 0, "no red pixels found... color may not have been honored"

    def test_zero_rotation_paints_horizontally(self):
        """rotation=0 means text is horizontal, pixels in the vertical
        sides should be transparent (text doesn't reach there)."""
        data = make_text_watermark(["X"], size=600, rotation=0)
        img = Image.open(io.BytesIO(data))
        # Top/bottom strips should have no painted pixels
        for y in (0, 599):
            for x in range(0, 600, 50):
                assert img.getpixel((x, y))[3] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Presets (Decision 6)
# ──────────────────────────────────────────────────────────────────────────────

class TestPresets:

    def test_three_presets_exist(self):
        assert set(PRESETS.keys()) == {"confidential", "draft", "copy"}

    def test_preset_is_dataclass_frozen(self):
        p = PRESETS["confidential"]
        assert isinstance(p, WatermarkPreset)
        with pytest.raises(Exception):  # FrozenInstanceError
            p.rotation = 0.0  # type: ignore[misc]

    def test_using_preset_produces_valid_png(self):
        for name in PRESETS:
            data = make_text_watermark(preset=name)
            assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_preset_default_lines_used_when_no_lines_passed(self):
        """Calling with preset only should use the preset's default text."""
        # We can't directly read the text from the PNG, but we verify the
        # call succeeds (it would fail with ValueError if no lines were
        # available).
        data = make_text_watermark(preset="confidential")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_explicit_lines_override_preset(self):
        """Passing lines AND preset"""
        # If lines were ignored we'd be using preset's default text instead.
        # We can't read text, but at least confirm the call works.
        data = make_text_watermark(["Override"], preset="confidential")
        assert data[:8] == b"\x89PNG\r\n\x1a\n"

    def test_explicit_color_overrides_preset(self):
        """Explicit color wins over the preset's color."""
        data = make_text_watermark(
            preset="confidential", color=(0, 255, 0, 255),
        )
        img = Image.open(io.BytesIO(data))
        # Green pixels should be present
        greens = 0
        for x in range(0, img.size[0], 50):
            for y in range(0, img.size[1], 50):
                r, g, b, a = img.getpixel((x, y))
                if a > 0 and g > 200 and r < 80 and b < 80:
                    greens += 1
        assert greens > 0, "explicit green color did not override preset"

    def test_unknown_preset_raises_with_available_list(self):
        with pytest.raises(ValueError) as exc:
            make_text_watermark(preset="nonexistent")
        msg = str(exc.value).lower()
        # The error must mention the available presets
        for name in ("confidential", "draft", "copy"):
            assert name in msg


# ──────────────────────────────────────────────────────────────────────────────
# Font path override
# ──────────────────────────────────────────────────────────────────────────────

class TestFontPath:

    def test_invalid_font_path_falls_back(self):
        """If font_path doesn't exist, fall back to platform default
        (don't crash)."""
        data = make_text_watermark(
            ["test"], font_path="/nonexistent/font.ttf",
        )
        assert data[:8] == b"\x89PNG\r\n\x1a\n"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

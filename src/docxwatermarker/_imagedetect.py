"""
Image enumeration, marker detection, and marker generation.

This module is INTERNAL. It knows about image file formats (just enough
to identify them by magic bytes and read dimensions via Pillow) and about
the docxwatermarker marker convention, but not about .docx semantics.

Design notes:

  - We scan only `word/media/` (Decision 1). Other locations where images
    might technically live in OOXML (word/embeddings/, ppt/media/, etc.)
    are out of scope: docxwatermarker targets Word documents, and Word puts
    inserted images in word/media/.

  - Format identification uses magic bytes only, never the file extension.
    Extensions in OOXML packages can lie, magic bytes can't.

  - Dimensions come from Pillow. If Pillow can't decode the file (truncated,
    corrupted), we return width=0/height=0 and keep the entry visible in
    the listing. Silently dropping a "broken" image would hide it from
    inspect/debug.

  - The marker is a PNG containing an iTXt/tEXt chunk with our marker
    string (Decision 3, variant C). We don't parse the PNG chunk structure
    properly, Pillow handles writing, and reading just checks if the
    marker string appears in the first ~512 bytes of the file (cheap,
    unambiguous in practice).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, PngImagePlugin, UnidentifiedImageError

from docxwatermarker._zipops import ZipEntry


# The directory inside the .docx package where Word stores inserted images.
_MEDIA_DIR = "word/media/"

# Marker string embedded in PNGs produced by make_marker_png().
# We look for this verbatim in the early bytes of a PNG to identify markers.
# Versioned so we can evolve the marker without breaking detection on
# already-deployed templates.
MARKER_TAG = "docxwatermarker-marker-v1"

# Default canvas size for make_marker_png. Matches what a typical Word
# page-anchored watermark expects (a square is rotation-friendly).
_DEFAULT_MARKER_SIZE = 1600

# How many bytes of the file to inspect when looking for the marker.
# 512 is safely past the PNG header + any text chunk Pillow emits at the
# top of the file.
_MARKER_SEARCH_LIMIT = 512


# Magic bytes by format. We list every format we want to recognize; the
# tuple is the byte prefix. Multiple prefixes per format are supported
# (e.g. TIFF has little-endian and big-endian variants).
_MAGIC: dict[str, tuple[bytes, ...]] = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    "bmp": (b"BM",),
    "tiff": (b"II*\x00", b"MM\x00*"),
    "webp": (b"RIFF",),  # plus "WEBP" at offset 8; checked below
}


@dataclass(frozen=True)
class ImageInfo:
    """Metadata for a single image inside a .docx, value-object semantics.

    Attributes:
        path:       internal path inside the zip (e.g. "word/media/image1.png")
        format:     lowercase format name ("png", "jpeg", "gif", ...)
        width:      width in pixels, or 0 if undecodable
        height:     height in pixels, or 0 if undecodable
        size_bytes: raw byte length of the entry's content
        is_marker:  True if this is a PNG carrying the docxwatermarker
                    marker (see make_marker_png / is_marker_image). False
                    for non-PNGs and PNGs without the marker.
    """

    path: str
    format: str
    width: int
    height: int
    size_bytes: int
    is_marker: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Format detection by magic bytes
# ──────────────────────────────────────────────────────────────────────────────

def _detect_format(data: bytes) -> str | None:
    """Return the format name for `data`, or None if no signature matches."""
    if len(data) < 4:
        return None
    for fmt, prefixes in _MAGIC.items():
        for prefix in prefixes:
            if data.startswith(prefix):
                # WebP is RIFF with "WEBP" at offset 8, disambiguate from
                # other RIFF-based formats (WAV, AVI) by checking that.
                if fmt == "webp":
                    if len(data) >= 12 and data[8:12] == b"WEBP":
                        return "webp"
                    continue
                return fmt
    return None


# ──────────────────────────────────────────────────────────────────────────────
# list_images
# ──────────────────────────────────────────────────────────────────────────────

def list_images(entries: dict[str, ZipEntry]) -> list[ImageInfo]:
    """Enumerate images inside word/media/.

    Returns ImageInfo for every entry under word/media/ that has a
    recognized image format magic-byte signature. Entries elsewhere in
    the archive are ignored. Non-image files in word/media/ (e.g. a stray
    .txt) are also ignored

    Order matches the order of entries in the input dict, which for
    `read_zip_entries` output reflects the central-directory order of
    the source archive, which in turn typically matches insertion order
    in Word. If Pillow cannot decode an image (truncated, corrupted), the entry
    is still returned with width=0 and height=0.
    """
    out: list[ImageInfo] = []
    for path, entry in entries.items():
        # OOXML path comparison is case-insensitive in practice; Word always
        # writes lowercase "word/media/" but tools that round-trip a .docx
        # can change capitalization. Compare lowercased to be safe.
        if not path.lower().startswith(_MEDIA_DIR):
            continue
        fmt = _detect_format(entry.data)
        if fmt is None:
            continue
        width, height = _read_dimensions(entry.data)
        # Marker detection is only meaningful for PNGs (the marker is a
        # tEXt chunk); cheap enough to compute eagerly for every image.
        marker = fmt == "png" and is_marker_image(entry.data)
        out.append(ImageInfo(
            path=path,
            format=fmt,
            width=width,
            height=height,
            size_bytes=len(entry.data),
            is_marker=marker,
        ))
    return out


def _read_dimensions(data: bytes) -> tuple[int, int]:
    """Try to read (width, height) from image bytes. Returns (0, 0) on failure."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            return img.size  # (width, height)
    except (UnidentifiedImageError, OSError, ValueError):
        return (0, 0)


# ──────────────────────────────────────────────────────────────────────────────
# Marker generation and detection
# ──────────────────────────────────────────────────────────────────────────────

def make_marker_png(size: int = _DEFAULT_MARKER_SIZE) -> bytes:
    """Generate a PNG containing the docxwatermarker marker.

    The PNG is fully transparent (RGBA all zeros), `size`x`size`, with a
    tEXt metadata chunk holding MARKER_TAG. Insert this PNG into your Word
    template as a page-anchored placeholder; docxwatermarker can then identify
    it unambiguously via ImageMatcher.by_marker().
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # PngInfo lets us attach text metadata that ends up as a tEXt chunk
    # near the top of the PNG file. We use a fixed key ("Description")
    # because it's the standard PNG metadata key and tools that strip
    # "custom" chunks tend to keep this one.
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Description", MARKER_TAG)

    buf = io.BytesIO()
    img.save(buf, "PNG", pnginfo=meta, optimize=True)
    return buf.getvalue()


def is_marker_image(data: bytes) -> bool:
    """True if `data` is a PNG carrying the docxwatermarker marker.

    We do a cheap substring search in the early bytes of the file rather
    than parsing PNG chunks properly.
    """
    if not data.startswith(_MAGIC["png"][0]):
        return False
    head = data[:_MARKER_SEARCH_LIMIT]
    return MARKER_TAG.encode("ascii") in head

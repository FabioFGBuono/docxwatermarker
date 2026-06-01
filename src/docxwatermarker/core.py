"""
Public API
Template and ImageMatcher.

This module wires together the internal helpers (_zipops, _imagedetect)
into the user-facing API. Orchestration only, no low-level
zip or image logic.

The Template object is immutable, replace_image() returns a new Template
wrapping the modified zip bytes. This makes chaining safe and matches
the way users naturally think about "version A -> version B" of a document. 
The ImageMatcher, given the list of images,
discovered in the docx (plus access to their bytes), pick exactly one or
raise. Three strategies are provided as classmethods:

    ImageMatcher.auto()        - marker first, then square-PNG heuristic
    ImageMatcher.by_filename() - exact internal path match
    ImageMatcher.by_marker()   - find the unique marker PNG
"""

from __future__ import annotations

import io
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Union, Callable

from PIL import Image as _PILImage, UnidentifiedImageError

from docxwatermarker._zipops import ZipEntry, read_zip_entries, write_zip
from docxwatermarker._imagedetect import (
    ImageInfo,
    list_images,
    _detect_format,
)
from docxwatermarker._invariants import require, ensure
from docxwatermarker._logging import get_logger
from docxwatermarker.errors import (
    ImageNotFoundError,
    MultipleImagesError,
    FormatMismatchError,
)

_logger = get_logger(__name__)


# The user-facing union of accepted image inputs for replace_image().
ImageInput = Union[bytes, Path, _PILImage.Image]


# ──────────────────────────────────────────────────────────────────────────────
# ImageMatcher
# ──────────────────────────────────────────────────────────────────────────────

# Default minimum side for the auto heuristic, large enough to filter out
# small decorative images, lenient enough not to require huge templates.
_AUTO_MIN_SIDE = 800


@dataclass(frozen=True)
class ImageMatcher:
    """Strategy for selecting one image inside a docx.

    Built via classmethods (auto, by_filename, by_marker), not directly.

    A matcher is a pure function over the discovered images + their raw
    bytes; it returns the internal path of exactly one image, or raises.
    """

    # Internal: the actual selection function. Set by the classmethods.
    # Signature: (images: list[ImageInfo], entries: dict[str, ZipEntry]) -> str
    _selector: Callable[[list[ImageInfo], dict[str, ZipEntry]], str]
    _description: str  # human-readable, used in error messages

    @classmethod
    def auto(cls, *, min_side: int = _AUTO_MIN_SIDE) -> "ImageMatcher":
        """Marker-first heuristic.

        Selection order:
          1. The unique PNG carrying the docxwatermarker marker.
          2. The unique square PNG with side >= min_side.

        If both stages produce zero or multiple candidates, raises
        ImageNotFoundError or MultipleImagesError.
        """
        def select(images: list[ImageInfo], entries: dict[str, ZipEntry]) -> str:
            # Stage 1: marker
            markers = [img.path for img in images if img.is_marker]
            if len(markers) == 1:
                _logger.debug("auto matcher: selected marker at %s", markers[0])
                return markers[0]
            if len(markers) > 1:
                raise MultipleImagesError(
                    "Multiple marker PNGs found in template; cannot disambiguate.",
                    matcher="auto",
                    matches=markers,
                )

            # Stage 2: heuristic (square PNG >= min_side)
            candidates = [
                img.path for img in images
                if img.format == "png"
                and img.width == img.height
                and img.width >= min_side
            ]
            if len(candidates) == 1:
                _logger.debug("auto matcher: selected by heuristic at %s",
                              candidates[0])
                return candidates[0]
            if len(candidates) == 0:
                raise ImageNotFoundError(
                    "No image matched the auto matcher: needed a marker PNG "
                    "or a unique square PNG of sufficient size.",
                    matcher="auto",
                    min_side=min_side,
                    candidates=[img.path for img in images],
                )
            raise MultipleImagesError(
                "Multiple square PNGs match the auto heuristic; "
                "pass an explicit matcher (by_filename or by_marker) to disambiguate.",
                matcher="auto",
                matches=candidates,
            )

        return cls(_selector=select, _description="auto")

    @classmethod
    def by_filename(cls, internal_path: str) -> "ImageMatcher":
        """Exact internal-path match, e.g. "word/media/image3.png"."""
        require(isinstance(internal_path, str), "internal_path must be a string",
                spec="P:by_filename")
        require(len(internal_path) > 0, "internal_path must not be empty",
                spec="P:by_filename")

        def select(images: list[ImageInfo], entries: dict[str, ZipEntry]) -> str:
            for img in images:
                if img.path == internal_path:
                    return img.path
            raise ImageNotFoundError(
                f"No image with internal path {internal_path!r}.",
                matcher="by_filename",
                target=internal_path,
                candidates=[img.path for img in images],
            )

        return cls(_selector=select, _description=f"by_filename({internal_path!r})")

    @classmethod
    def by_marker(cls) -> "ImageMatcher":
        """Find the unique PNG carrying the docxwatermarker marker.

        Use make_marker_png() to produce a placeholder. Insert it in your
        Word template, this matcher will then identify it unambiguously.
        """
        def select(images: list[ImageInfo], entries: dict[str, ZipEntry]) -> str:
            markers = [img.path for img in images if img.is_marker]
            if len(markers) == 1:
                return markers[0]
            if len(markers) == 0:
                raise ImageNotFoundError(
                    "No marker PNG found in template. Use make_marker_png() "
                    "to generate a placeholder and insert it in Word.",
                    matcher="by_marker",
                    candidates=[img.path for img in images],
                )
            raise MultipleImagesError(
                "Multiple marker PNGs found; only one is supported.",
                matcher="by_marker",
                matches=markers,
            )

        return cls(_selector=select, _description="by_marker")


# ──────────────────────────────────────────────────────────────────────────────
# Template
# ──────────────────────────────────────────────────────────────────────────────

class Template:
    """A .docx file opened for image replacement.

    Template is immutable: replace_image() returns a new Template wrapping
    the modified zip bytes. The original is never mutated, which makes
    chaining and reuse safe.

    Typical usage:

        from docxwatermarker import Template, make_marker_png

        tmpl = Template.open("template.docx")
        out = tmpl.replace_image(new_png_bytes)
        out.save("personalized.docx")
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: dict[str, ZipEntry]) -> None:
        """Low-level constructor. Prefer Template.open() or from_bytes()."""
        # Callers cannot mutate the dict they
        # passed in, and the internal mapping rejects writes. replace_image
        # never mutates this mapping; it builds a fresh dict and returns a
        # new Template.
        self._entries: types.MappingProxyType[str, ZipEntry] = (
            types.MappingProxyType(dict(entries))
        )

    @classmethod
    def open(cls, path: str | Path) -> "Template":
        """Read a .docx from disk and return a Template instance."""
        p = Path(path)
        data = p.read_bytes()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Template":
        """Build a Template from raw bytes (e.g. an in-memory zip).

        Raises zipfile.BadZipFile if the bytes are not a valid zip.
        """
        require(isinstance(data, (bytes, bytearray)),
                "data must be bytes", spec="P:from_bytes",
                got_type=type(data).__name__)
        entries = read_zip_entries(bytes(data))
        return cls(entries)

    def list_images(self) -> list[ImageInfo]:
        """Return metadata for every image in word/media/."""
        return list_images(self._entries)

    def replace_image(
        self,
        new_image: ImageInput,
        *,
        matcher: ImageMatcher | None = None,
        validate_image: bool = True,
    ) -> "Template":
        """Return a new Template with one image replaced.

        Parameters
        ----------
        new_image
            The replacement image. Accepted types:
              - bytes: raw image data, already encoded in the target format
              - Path:  filesystem path to an image file
              - PIL.Image.Image: a Pillow image, will be encoded as PNG
        matcher
            How to find the image to replace. Defaults to ImageMatcher.auto().
        validate_image
            If True (default), the replacement bytes are decoded with Pillow
            after the format check, to catch files that have a valid magic
            signature but corrupt body. Set to False to skip the decode pass
            (faster, but a malformed image will silently produce a .docx
            that Word refuses to open).

        Returns
        -------
        Template
            A new Template wrapping the modified zip. The original is unchanged.

        Raises
        ------
        ImageNotFoundError
            No image matched the selector.
        MultipleImagesError
            More than one image matched and the matcher does not auto-pick.
        FormatMismatchError
            The replacement image's format differs from the target's, or
            (with validate_image=True) the bytes have a valid signature but
            cannot be decoded.
        """
        if matcher is None:
            matcher = ImageMatcher.auto()

        # 1) Resolve which image to replace.
        images = list_images(self._entries)
        target_path = matcher._selector(images, self._entries)
        target_info = next(i for i in images if i.path == target_path)

        # 2) Normalize the input into bytes.
        raw = _normalize_image_input(new_image)

        # 3) Format consistency check.
        input_format = _detect_format(raw)
        if input_format != target_info.format:
            raise FormatMismatchError(
                "Replacement image format does not match target.",
                target_path=target_path,
                target_format=target_info.format,
                input_format=input_format,
            )

        # 3b) Optional decode-time validation: catch files with a valid
        # magic signature but a corrupt body. Pillow's verify() is cheap
        # and catches most real-world breakage (truncated PNGs, wrong
        # length fields, etc.) without fully decoding the pixel data.
        if validate_image:
            try:
                with _PILImage.open(io.BytesIO(raw)) as probe:
                    probe.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
                raise FormatMismatchError(
                    "Replacement bytes have a valid magic signature but "
                    "cannot be decoded as an image.",
                    target_path=target_path,
                    target_format=target_info.format,
                    input_format=input_format,
                    decode_error=repr(exc),
                ) from exc

        # 4) Build the modified entry, preserving template metadata.
        original_entry = self._entries[target_path]
        new_entry = ZipEntry.modified(
            filename=target_path,
            data=raw,
            template=original_entry,
        )

        # 5) Compose new entries dict, preserving order.
        new_entries = dict(self._entries)
        new_entries[target_path] = new_entry

        # Invariant: the new template has the same set of entries.
        ensure(
            set(new_entries.keys()) == set(self._entries.keys()),
            "replace_image must not add or remove zip entries",
            spec="I2",
            before=sorted(self._entries.keys()),
            after=sorted(new_entries.keys()),
        )

        _logger.info("replaced image at %s (%d bytes -> %d bytes)",
                     target_path, len(original_entry.data), len(raw))

        return Template(new_entries)

    def save(self, path: str | Path) -> Path:
        """Write the docx to disk. Returns the resolved Path."""
        p = Path(path).resolve()
        p.write_bytes(self.to_bytes())
        return p

    def to_bytes(self) -> bytes:
        """Return the docx as raw bytes (useful for in-memory pipelines)."""
        return write_zip(self._entries)


# ──────────────────────────────────────────────────────────────────────────────
# Internal: input normalization (Decision 3, variant C)
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_image_input(value: ImageInput) -> bytes:
    """Convert any accepted ImageInput type into raw bytes.

    - bytes/bytearray/memoryview: returned as bytes
    - Path or str-like path: read from disk
    - PIL.Image.Image: encoded as PNG to a memory buffer

    Other types raise TypeError with a clear message.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, Path):
        return value.read_bytes()
    if isinstance(value, _PILImage.Image):
        buf = io.BytesIO()
        value.save(buf, "PNG")
        return buf.getvalue()
    raise TypeError(
        f"replace_image: unsupported input type {type(value).__name__}; "
        f"expected bytes, Path, or PIL.Image.Image"
    )

"""
Tests for core: Template and ImageMatcher.

This is where _zipops and _imagedetect are wired together into the public
API. The behaviors pinned by these tests:

  - Template.open(path) reads a .docx from disk
  - Template.from_bytes(data) builds from raw bytes (in-memory path)
  - Template.list_images() returns ImageInfo list (Decision 1)
  - Template is immutable: replace_image() returns a new Template
  - ImageMatcher: auto, by_filename, by_marker — each selects correctly
  - auto matcher: marker first, then heuristic (Decision 4)
  - replace_image accepts bytes/Path/PIL.Image (Decision 3)
  - replace_image rejects format mismatches with FormatMismatchError (3b)
  - errors carry rich context per the foundation contract
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker import (
    Template,
    ImageMatcher,
    ImageInfo,
    make_marker_png,
    ImageNotFoundError,
    MultipleImagesError,
    FormatMismatchError,
)


# ──────────────────────────────────────────────────────────────────────────────
# build .docx files in memory for each test
# ──────────────────────────────────────────────────────────────────────────────

def _png(width: int, height: int, color=(255, 0, 0, 0)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _jpeg(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), (0, 128, 255))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def _make_docx(media_files: dict[str, bytes]) -> bytes:
    """Assemble a minimal .docx with the given files under word/media/.
    Always includes the OOXML skeleton."""
    base = {
        "[Content_Types].xml": b"<types/>",
        "_rels/.rels": b"<rels/>",
        "word/document.xml": b"<doc/>",
        "word/_rels/document.xml.rels": b"<rels/>",
    }
    base.update({f"word/media/{name}": data for name, data in media_files.items()})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in base.items():
            zf.writestr(name, data)
    return buf.getvalue()


@pytest.fixture
def docx_with_marker() -> bytes:
    """A docx whose word/media contains exactly one marker PNG."""
    return _make_docx({"image1.png": make_marker_png(1600)})


@pytest.fixture
def docx_with_square_png() -> bytes:
    """A docx with one non-marker square PNG suitable for auto heuristic."""
    return _make_docx({"image1.png": _png(1600, 1600)})


@pytest.fixture
def docx_with_multiple_images() -> bytes:
    """A docx with two square PNGs and a small one — auto without marker
    would be ambiguous."""
    return _make_docx({
        "image1.png": _png(1600, 1600),
        "image2.png": _png(1600, 1600),
        "image3.png": _png(50, 50),  # too small to match heuristic
    })


@pytest.fixture
def docx_with_marker_and_others() -> bytes:
    """A docx with a marker PNG plus other images. auto must pick the marker."""
    return _make_docx({
        "image1.png": _png(1600, 1600),  # plain square
        "image2.png": make_marker_png(800),  # marker, smaller
        "image3.jpeg": _jpeg(400, 300),
    })


@pytest.fixture
def docx_no_images() -> bytes:
    return _make_docx({})


# ──────────────────────────────────────────────────────────────────────────────
# Template.open / from_bytes
# ──────────────────────────────────────────────────────────────────────────────

class TestTemplateConstruction:

    def test_open_reads_file_from_disk(self, tmp_path, docx_with_marker):
        path = tmp_path / "template.docx"
        path.write_bytes(docx_with_marker)
        tmpl = Template.open(path)
        assert tmpl is not None

    def test_open_accepts_str_path(self, tmp_path, docx_with_marker):
        path = tmp_path / "template.docx"
        path.write_bytes(docx_with_marker)
        tmpl = Template.open(str(path))
        assert tmpl is not None

    def test_open_missing_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError)):
            Template.open(tmp_path / "nonexistent.docx")

    def test_open_invalid_docx_raises(self, tmp_path):
        bad = tmp_path / "bad.docx"
        bad.write_bytes(b"this is not a zip")
        with pytest.raises(Exception):
            Template.open(bad)

    def test_from_bytes_works(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        assert tmpl is not None

    def test_from_bytes_invalid_raises(self):
        with pytest.raises(Exception):
            Template.from_bytes(b"not a zip")


# ──────────────────────────────────────────────────────────────────────────────
# Template.list_images
# ──────────────────────────────────────────────────────────────────────────────

class TestListImages:

    def test_returns_list_of_image_info(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        images = tmpl.list_images()
        assert isinstance(images, list)
        assert all(isinstance(i, ImageInfo) for i in images)
        assert len(images) == 1

    def test_multiple_images_listed(self, docx_with_multiple_images):
        tmpl = Template.from_bytes(docx_with_multiple_images)
        images = tmpl.list_images()
        assert len(images) == 3
        paths = {i.path for i in images}
        assert paths == {
            "word/media/image1.png",
            "word/media/image2.png",
            "word/media/image3.png",
        }

    def test_no_images_returns_empty(self, docx_no_images):
        tmpl = Template.from_bytes(docx_no_images)
        assert tmpl.list_images() == []


# ──────────────────────────────────────────────────────────────────────────────
# ImageMatcher: by_filename
# ──────────────────────────────────────────────────────────────────────────────

class TestMatcherByFilename:

    def test_finds_exact_match(self, docx_with_multiple_images):
        tmpl = Template.from_bytes(docx_with_multiple_images)
        matcher = ImageMatcher.by_filename("word/media/image2.png")
        result = tmpl.replace_image(_png(1600, 1600), matcher=matcher)
        assert result is not None

    def test_missing_path_raises_image_not_found(self, docx_with_multiple_images):
        tmpl = Template.from_bytes(docx_with_multiple_images)
        matcher = ImageMatcher.by_filename("word/media/does_not_exist.png")
        with pytest.raises(ImageNotFoundError) as exc:
            tmpl.replace_image(_png(100, 100), matcher=matcher)
        # Error carries useful context
        assert "does_not_exist" in str(exc.value) or \
               "does_not_exist" in repr(exc.value.context)


# ──────────────────────────────────────────────────────────────────────────────
# ImageMatcher: by_marker
# ──────────────────────────────────────────────────────────────────────────────

class TestMatcherByMarker:

    def test_finds_marker(self, docx_with_marker_and_others):
        tmpl = Template.from_bytes(docx_with_marker_and_others)
        matcher = ImageMatcher.by_marker()
        # Must succeed: there is exactly one marker
        tmpl.replace_image(_png(800, 800), matcher=matcher)

    def test_no_marker_raises(self, docx_with_square_png):
        tmpl = Template.from_bytes(docx_with_square_png)
        matcher = ImageMatcher.by_marker()
        with pytest.raises(ImageNotFoundError):
            tmpl.replace_image(_png(100, 100), matcher=matcher)


# ──────────────────────────────────────────────────────────────────────────────
# ImageMatcher: auto
# ──────────────────────────────────────────────────────────────────────────────

class TestMatcherAuto:

    def test_auto_prefers_marker(self, docx_with_marker_and_others):
        """Decision 4: when a marker exists, auto picks it even if there
        are other square PNGs that would match the heuristic."""
        tmpl = Template.from_bytes(docx_with_marker_and_others)
        # Replace using auto with a small PNG
        new = _png(800, 800)
        result = tmpl.replace_image(new, matcher=ImageMatcher.auto())
        # The marker entry (image2.png) was the one replaced
        reread = result.list_images()
        # Find image2 and verify its size matches the new image
        img2 = next(i for i in reread if i.path == "word/media/image2.png")
        assert (img2.width, img2.height) == (800, 800)
        # image1 (a non-marker 1600x1600) is unchanged
        img1 = next(i for i in reread if i.path == "word/media/image1.png")
        assert (img1.width, img1.height) == (1600, 1600)

    def test_auto_falls_back_to_heuristic(self, docx_with_square_png):
        """Without a marker, auto picks the unique square PNG."""
        tmpl = Template.from_bytes(docx_with_square_png)
        result = tmpl.replace_image(_png(1600, 1600), matcher=ImageMatcher.auto())
        assert result is not None

    def test_auto_raises_on_ambiguity(self, docx_with_multiple_images):
        """Two square PNGs, no marker → ambiguous, must raise."""
        tmpl = Template.from_bytes(docx_with_multiple_images)
        with pytest.raises(MultipleImagesError) as exc:
            tmpl.replace_image(_png(1600, 1600), matcher=ImageMatcher.auto())
        # Error carries the matched paths
        assert "matches" in exc.value.context
        assert len(exc.value.context["matches"]) == 2

    def test_auto_raises_on_no_candidates(self, docx_no_images):
        tmpl = Template.from_bytes(docx_no_images)
        with pytest.raises(ImageNotFoundError):
            tmpl.replace_image(_png(100, 100), matcher=ImageMatcher.auto())

    def test_default_matcher_is_auto(self, docx_with_marker):
        """Calling replace_image() without matcher uses auto()."""
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(_png(1600, 1600))  # no matcher kwarg
        assert result is not None


# ──────────────────────────────────────────────────────────────────────────────
# replace_image: input type dispatch (Decision 3)
# ──────────────────────────────────────────────────────────────────────────────

class TestReplaceImageInputTypes:

    def test_accepts_bytes(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(_png(800, 800))
        assert result is not None

    def test_accepts_path(self, tmp_path, docx_with_marker):
        png_path = tmp_path / "new.png"
        png_path.write_bytes(_png(800, 800))
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(png_path)
        assert result is not None

    def test_accepts_pil_image(self, docx_with_marker):
        pil_img = Image.new("RGBA", (800, 800), (0, 255, 0, 128))
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(pil_img)
        assert result is not None
        # The image was encoded as PNG and substituted
        new_info = next(i for i in result.list_images()
                        if i.path == "word/media/image1.png")
        assert new_info.format == "png"
        assert (new_info.width, new_info.height) == (800, 800)

    def test_rejects_unsupported_type(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        with pytest.raises(TypeError):
            tmpl.replace_image(12345)  # int is not a supported input

    def test_path_to_missing_file_raises(self, tmp_path, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        with pytest.raises((FileNotFoundError, OSError)):
            tmpl.replace_image(tmp_path / "nope.png")


# ──────────────────────────────────────────────────────────────────────────────
# replace_image: format mismatch (Decision 3b)
# ──────────────────────────────────────────────────────────────────────────────

class TestFormatMismatch:

    def test_jpeg_into_png_slot_raises(self, docx_with_marker):
        """Target is PNG; we pass JPEG bytes; must raise FormatMismatchError."""
        tmpl = Template.from_bytes(docx_with_marker)
        jpeg = _jpeg(800, 800)
        with pytest.raises(FormatMismatchError) as exc:
            tmpl.replace_image(jpeg)
        ctx = exc.value.context
        assert ctx.get("target_format") == "png"
        assert ctx.get("input_format") == "jpeg"

    def test_png_into_png_slot_works(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        tmpl.replace_image(_png(800, 800))


# ──────────────────────────────────────────────────────────────────────────────
# Immutability
# ──────────────────────────────────────────────────────────────────────────────

class TestImmutability:

    def test_replace_image_returns_new_template(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(_png(800, 800))
        assert result is not tmpl

    def test_original_template_unchanged_after_replace(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        original_image = tmpl.list_images()[0]
        # original was a 1600x1600 marker
        assert (original_image.width, original_image.height) == (1600, 1600)
        # Replace with a different-sized image
        tmpl.replace_image(_png(400, 400))
        # Original template still has the marker at 1600x1600
        same = tmpl.list_images()[0]
        assert (same.width, same.height) == (1600, 1600)

    def test_chained_replacements(self, docx_with_marker):
        """A → B → C: each step produces a new Template."""
        a = Template.from_bytes(docx_with_marker)
        b = a.replace_image(_png(800, 800))
        c = b.replace_image(_png(400, 400), matcher=ImageMatcher.by_filename(
            "word/media/image1.png"
        ))
        assert a is not b
        assert b is not c
        a_img = a.list_images()[0]
        b_img = b.list_images()[0]
        c_img = c.list_images()[0]
        assert (a_img.width, a_img.height) == (1600, 1600)
        assert (b_img.width, b_img.height) == (800, 800)
        assert (c_img.width, c_img.height) == (400, 400)

    def test_internal_mapping_is_frozen(self, docx_with_marker):
        """The internal entries mapping rejects mutation.

        Backs Property I1 in the formal spec, the constructor freezes the
        dict with types.MappingProxyType, so the contents cannot be altered
        in place, not even through the private attribute.
        """
        tmpl = Template.from_bytes(docx_with_marker)
        existing = next(iter(tmpl._entries.values()))
        with pytest.raises(TypeError):
            tmpl._entries["word/media/injected.png"] = existing
        with pytest.raises(TypeError):
            del tmpl._entries[next(iter(tmpl._entries))]


# ──────────────────────────────────────────────────────────────────────────────
# save / to_bytes
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveAndToBytes:

    def test_save_writes_file(self, tmp_path, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(_png(800, 800))
        out_path = tmp_path / "out.docx"
        returned = result.save(out_path)
        assert out_path.exists()
        assert returned == out_path.resolve()

    def test_save_creates_valid_docx(self, tmp_path, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        result = tmpl.replace_image(_png(800, 800))
        out_path = tmp_path / "out.docx"
        result.save(out_path)
        # Reopen via Template.open: must succeed
        reopened = Template.open(out_path)
        images = reopened.list_images()
        assert len(images) == 1
        assert (images[0].width, images[0].height) == (800, 800)

    def test_to_bytes_returns_bytes(self, docx_with_marker):
        tmpl = Template.from_bytes(docx_with_marker)
        data = tmpl.to_bytes()
        assert isinstance(data, bytes)
        # It's a valid zip
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert "word/media/image1.png" in zf.namelist()

    def test_to_bytes_roundtrip(self, docx_with_marker):
        """to_bytes ↔ from_bytes is a valid roundtrip."""
        tmpl = Template.from_bytes(docx_with_marker)
        new_tmpl = tmpl.replace_image(_png(500, 500))
        reborn = Template.from_bytes(new_tmpl.to_bytes())
        info = reborn.list_images()[0]
        assert (info.width, info.height) == (500, 500)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

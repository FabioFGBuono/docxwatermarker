"""
docxwatermarker
Replace images inside .docx files while preserving layout.

Public API:

    Template            - wraps a .docx, exposes list_images() / replace_image()
                          / save() / to_bytes()
    ImageMatcher        - strategy for selecting which image to replace
                          (.auto / .by_filename / .by_marker)
    ImageInfo           - metadata returned by Template.list_images()
    make_marker_png     - generate a placeholder PNG carrying the docxwatermarker
                          marker (insert in Word, then match with by_marker)

    enable_debug, disable_debug, is_debug_enabled
        Control debug-mode logging and internal invariant checks.

    configure_invariants
        Switch ensure() between warn-and-continue (default) and raise.

Exceptions:
    DocxWatermarkerError       - base class for all library errors
    ImageNotFoundError     - no image matched the selector
    MultipleImagesError    - selector matched more than one image
    FormatMismatchError    - replacement image format != target format
    PDFConversionError     - LibreOffice missing or conversion failed
    InvariantError         - internal contract violation
"""

from docxwatermarker.core import Template, ImageMatcher
from docxwatermarker._imagedetect import ImageInfo, make_marker_png
from docxwatermarker.watermark import (
    make_text_watermark,
    WatermarkPreset,
    PRESETS,
)
from docxwatermarker._logging import (
    enable_debug,
    disable_debug,
    is_debug_enabled,
)
from docxwatermarker._invariants import (
    configure_invariants,
    is_ensure_raising,
)
from docxwatermarker.errors import (
    DocxWatermarkerError,
    ImageNotFoundError,
    MultipleImagesError,
    PDFConversionError,
    FormatMismatchError,
    InvariantError,
)

__all__ = [
    # Core
    "Template",
    "ImageMatcher",
    "ImageInfo",
    "make_marker_png",
    # Watermark
    "make_text_watermark",
    "WatermarkPreset",
    "PRESETS",
    # Debug / logging
    "enable_debug",
    "disable_debug",
    "is_debug_enabled",
    # Invariants
    "configure_invariants",
    "is_ensure_raising",
    # Exceptions
    "DocxWatermarkerError",
    "ImageNotFoundError",
    "MultipleImagesError",
    "PDFConversionError",
    "FormatMismatchError",
    "InvariantError",
]

__version__ = "0.1.0"

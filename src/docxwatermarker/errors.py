"""
Exception hierarchy for docxwatermarker.

All library-specific exceptions derive from DocxWatermarkerError, so callers
can catch everything with a single except clause if desired.

Every exception carries structured context in addition to its human-readable
message. Access it via the `.context` attribute or `.to_dict()` for
machine-readable output (e.g. JSON logs, error reporting tools).

Example:
    try:
        template.replace_image(new_image)
    except MultipleImagesError as e:
        print(e)                          # human-readable
        print(e.to_dict())                # {"error": ..., "context": {...}}
        print(e.context["matches"])       # ["word/media/image1.png", ...]
"""

from __future__ import annotations

from typing import Any


class DocxWatermarkerError(Exception):
    """Base class for all docxwatermarker exceptions.

    Subclasses should accept a primary message and any number of keyword
    arguments that will be stored in the `context` dict. The string form
    appends a compact rendering of the context for ergonomic debugging.
    """

    def __init__(self, message: str, **context: Any) -> None:
        self.message = message
        self.context: dict[str, Any] = context
        super().__init__(self._render())

    def _render(self) -> str:
        if not self.context:
            return self.message
        parts = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"{self.message} [{parts}]"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the error.

        The context dict is sanitized recursively: any value that is not
        directly JSON-compatible (bool, int, float, str, None, list, dict,
        tuple) is converted to its repr() form. This guarantees that
        ``json.dumps(e.to_dict())`` always succeeds.

        Tuples become lists (JSON has no tuple). Dict keys that are not
        strings are coerced via str().
        """
        return {
            "error": type(self).__name__,
            "message": self.message,
            "context": _json_safe(self.context),
        }


class ImageNotFoundError(DocxWatermarkerError):
    """No image inside the docx matched the requested selector.

    Common context keys:
        docx_path:   the .docx that was searched
        matcher:     description of the matcher used
        candidates:  list of images that were considered but rejected
    """


class MultipleImagesError(DocxWatermarkerError):
    """The selector matched more than one image and the matcher does not
    auto-disambiguate.

    Common context keys:
        docx_path:   the .docx that was searched
        matches:     list of internal paths that matched
    """


class PDFConversionError(DocxWatermarkerError):
    """PDF conversion via LibreOffice failed.

    Common context keys:
        docx_path:    the source .docx
        reason:       'not_found' | 'timeout' | 'nonzero_exit' | 'no_output'
        stderr:       last lines of soffice stderr (if available)
        exit_code:    soffice exit code (if available)
    """


class FormatMismatchError(DocxWatermarkerError):
    """The replacement image's format does not match the target image's format.

    docxwatermarker does not transcode: substituting a JPEG for a PNG would
    leave the package's Content_Types declaration inconsistent and the
    document might not open correctly. Re-encode the input to the target
    format before passing it in.

    Common context keys:
        target_path:    internal path of the image being replaced
        target_format:  format detected in the original image ("png", ...)
        input_format:   format detected in the replacement bytes
    """


class InvariantError(DocxWatermarkerError):
    """An internal invariant was violated.

    Raised only when the invariant check is configured to raise (opt-in
    via configure_invariants(raise_on_failure=True)) or when a `require()`
    precondition fails.

    Common context keys:
        kind:        'require' (precondition) or 'ensure' (postcondition)
                     - reserved, the require/ensure functions refuse to
                     accept 'kind' as a user-supplied kwarg.
        ...:         arbitrary context passed at check time
    """


# ──────────────────────────────────────────────────────────────────────────────
# Internal helper: recursive sanitization for JSON output.
# ──────────────────────────────────────────────────────────────────────────────

# Types that json.dumps handles natively. Note: bool is a subclass of int but
# json handles both correctly, no special case needed.
_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into a JSON-serializable form.

    Rules:
      - primitives (str, int, float, bool, None) pass through unchanged
      - dict: keys coerced to str, values sanitized recursively
      - list / tuple: every element sanitized recursively; tuples become lists
      - anything else: replaced by repr(value)

    The repr() fallback is deliberate over str(): repr preserves type
    information (e.g. ``PosixPath('/tmp/x')`` vs ``/tmp/x``), which is
    more useful when debugging an error report.
    """
    if isinstance(value, _JSON_PRIMITIVES):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return repr(value)

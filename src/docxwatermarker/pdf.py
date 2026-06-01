"""
DOCX -> PDF conversion via headless LibreOffice.

This module shells out to soffice/libreoffice
with the right flags, captures result, and translates everything into the
library's exception model. No fancy retries, no fallback engines.

Why LibreOffice and not pure Python? Because the existing pure-Python
options (docx2pdf, comtypes) either need Word installed (Windows-only)
or are wrappers over Office automation. LibreOffice headless is the only
cross-platform option that doesn't require commercial software.

Failure modes are pinned by PDFConversionError(reason=...):

    not_found            - LibreOffice binary not in PATH and no override given
    cannot_create_outdir - could not create the parent directory for the
                           output PDF (permissions, read-only FS, ...)
    timeout              - subprocess hit the timeout limit
    nonzero_exit         - soffice ran but exited with non-zero status
    no_output            - soffice exited 0 but did not produce the expected
                           file (LibreOffice occasionally does this silently)

The conversion uses an isolated UserInstallation profile (`-env:` arg) in
a temp directory. This avoids a notorious LibreOffice quirk: a running
GUI instance can prevent or hijack headless conversions.

Environment:
    DOCXWATERMARKER_SOFFICE   - explicit path to the LibreOffice binary,
                            takes precedence over PATH auto-detection.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from docxwatermarker._logging import get_logger
from docxwatermarker.errors import PDFConversionError

_logger = get_logger(__name__)

_ENV_VAR = "DOCXWATERMARKER_SOFFICE"
_DEFAULT_TIMEOUT = 180.0


def find_libreoffice() -> str | None:
    """Locate the LibreOffice executable, or return None if unavailable.

    Resolution order:
        1. DOCXWATERMARKER_SOFFICE environment variable, if set and pointing
           to an existing executable file.
        2. `soffice` in PATH (the canonical name).
        3. `libreoffice` in PATH (used by some Linux distros).

    Returns None if nothing usable is found. Callers can use this to
    degrade gracefully (e.g. CLI: warn the user and skip PDF generation).
    """
    # 1) Env var override
    env_val = os.environ.get(_ENV_VAR)
    if env_val:
        env_path = Path(env_val)
        if env_path.is_file() and os.access(env_path, os.X_OK):
            return str(env_path)
        _logger.warning(
            "DOCXWATERMARKER_SOFFICE=%r is not an executable file; "
            "falling back to auto-detect",
            env_val,
        )

    # 2/3) Auto-detect
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def to_pdf(
    docx_path: str | Path,
    output_path: str | Path | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    soffice_binary: str | None = None,
) -> Path:
    """Convert a .docx file to PDF using LibreOffice.

    Parameters
    ----------
    docx_path
        Source .docx file. Must exist.
    output_path
        Destination PDF path. If None, the PDF is written next to the
        source with the same stem and a .pdf extension.
    timeout
        Maximum seconds to wait for LibreOffice.
    soffice_binary
        Explicit path to soffice. If None, uses find_libreoffice() (which
        respects DOCXWATERMARKER_SOFFICE and falls back to PATH search).

    Returns
    -------
    Path
        The resolved Path of the produced PDF.

    Raises
    ------
    PDFConversionError
        With one of the documented reasons (not_found, timeout,
        nonzero_exit, no_output). The exception's `context` dict carries
        diagnostic data: stderr, exit_code, timeout, etc.
    """
    docx_path = Path(docx_path).resolve()

    # Locate soffice
    binary = soffice_binary or find_libreoffice()
    if not binary:
        raise PDFConversionError(
            "LibreOffice binary not found. Install LibreOffice or set "
            "DOCXWATERMARKER_SOFFICE to its path.",
            reason="not_found",
            docx_path=str(docx_path),
        )

    # soffice writes to outdir with the input's stem. Pick outdir to match
    # the user's desired final location (so we don't move files across
    # filesystems unnecessarily).
    if output_path is None:
        final_output = docx_path.with_suffix(".pdf")
    else:
        final_output = Path(output_path).resolve()
    outdir = final_output.parent
    try:
        outdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # Wrap to keep the library's exception contract: callers should
        # only need to catch PDFConversionError for I/O around conversion.
        raise PDFConversionError(
            "Cannot create the output directory for PDF conversion.",
            reason="cannot_create_outdir",
            docx_path=str(docx_path),
            outdir=str(outdir),
            os_error=repr(exc),
        ) from exc

    # The file soffice will actually produce. We may rename it afterwards
    # if the user requested a different filename.
    soffice_output = outdir / f"{docx_path.stem}.pdf"

    # Isolated user profile in a temp directory, avoids conflicts with any
    # running LibreOffice GUI instance. All conversion logic stays inside
    # this block so the profile is only cleaned up after we've finished
    # using soffice's output.
    with tempfile.TemporaryDirectory(prefix="docxwatermarker_lo_") as profile_dir:
        # The URL form is what soffice expects for this arg.
        profile_url = Path(profile_dir).as_uri()

        cmd = [
            binary,
            "--headless",
            f"-env:UserInstallation={profile_url}",
            "--convert-to", "pdf",
            "--outdir", str(outdir),
            str(docx_path),
        ]

        _logger.debug("running: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise PDFConversionError(
                "LibreOffice conversion exceeded timeout.",
                reason="timeout",
                docx_path=str(docx_path),
                timeout=timeout,
            )

        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[-500:]
            raise PDFConversionError(
                "LibreOffice exited with non-zero status.",
                reason="nonzero_exit",
                docx_path=str(docx_path),
                exit_code=result.returncode,
                stderr=stderr_tail,
            )

        # After subprocess, the file should exist where soffice was told to
        # put it. LibreOffice sometimes silently doesn't produce it.
        if not soffice_output.exists():
            raise PDFConversionError(
                "LibreOffice exited successfully but did not produce a PDF.",
                reason="no_output",
                docx_path=str(docx_path),
                expected_at=str(soffice_output),
            )

        # If the user wanted a different filename, rename now. This must
        # happen before we exit the `with` block so any failure here is
        # still inside the supervised region, though replace() on the same
        # filesystem is atomic and rarely fails.
        if soffice_output != final_output:
            soffice_output.replace(final_output)

    _logger.info("converted %s -> %s", docx_path, final_output)
    return final_output

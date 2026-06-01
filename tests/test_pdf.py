"""
Tests for pdf.py (DOCX to PDF conversion via LibreOffice)

These tests mock subprocess.run so they can run anywhere without needing
LibreOffice installed. The real end-to-end tests live in
test_pdf_integration.py and require LibreOffice.

Pinned contract:
  - find_libreoffice(): respects DOCXWATERMARKER_SOFFICE env var first, then
    auto-detects via shutil.which("soffice"|"libreoffice"). Returns None
    if nothing usable.
  - to_pdf():
      * raises PDFConversionError(reason="not_found") when no binary
      * builds the correct soffice command line (headless, convert-to pdf,
        outdir, isolated UserInstallation)
      * raises PDFConversionError with specific reason on each failure mode:
        "timeout", "nonzero_exit", "no_output"
      * returns the resolved output Path on success
      * honors explicit output_path, timeout, soffice_binary overrides
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker import PDFConversionError
from docxwatermarker.pdf import to_pdf, find_libreoffice


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_dummy_docx(path: Path) -> Path:
    """Write a placeholder file at `path`. We never actually read it in
    these tests — the subprocess is mocked — but to_pdf does check that
    the input exists, so we need a real file."""
    path.write_bytes(b"PK\x03\x04dummy_docx_placeholder")
    return path


def _make_fake_pdf(path: Path) -> Path:
    """Write a fake PDF that the mock will pretend soffice produced."""
    path.write_bytes(b"%PDF-1.7 fake pdf content\n%%EOF")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# find_libreoffice
# ──────────────────────────────────────────────────────────────────────────────

class TestFindLibreoffice:

    def test_env_var_takes_precedence(self, monkeypatch, tmp_path):
        """If DOCXWATERMARKER_SOFFICE is set to a real executable, use it."""
        fake = tmp_path / "my-custom-soffice"
        fake.write_text("#!/bin/sh\necho fake\n")
        fake.chmod(0o755)
        monkeypatch.setenv("DOCXWATERMARKER_SOFFICE", str(fake))
        result = find_libreoffice()
        assert result == str(fake)

    def test_env_var_pointing_to_nonexistent_is_ignored(self, monkeypatch, tmp_path):
        """A misconfigured env var must not crash; we fall through to auto-detect."""
        monkeypatch.setenv("DOCXWATERMARKER_SOFFICE", str(tmp_path / "does_not_exist"))
        # Result depends on what's installed on the host
        result = find_libreoffice()
        assert result is None or isinstance(result, str)

    def test_returns_string_when_soffice_in_path(self, monkeypatch):
        """When shutil.which finds soffice, return its full path."""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        with patch("docxwatermarker.pdf.shutil.which") as which:
            which.side_effect = lambda name: "/usr/bin/soffice" if name == "soffice" else None
            assert find_libreoffice() == "/usr/bin/soffice"

    def test_falls_back_to_libreoffice_name(self, monkeypatch):
        """Some distros only have `libreoffice` (not `soffice`)."""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        with patch("docxwatermarker.pdf.shutil.which") as which:
            which.side_effect = lambda name: (
                "/usr/bin/libreoffice" if name == "libreoffice" else None
            )
            assert find_libreoffice() == "/usr/bin/libreoffice"

    def test_returns_none_when_nothing_found(self, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        with patch("docxwatermarker.pdf.shutil.which", return_value=None):
            assert find_libreoffice() is None


# ──────────────────────────────────────────────────────────────────────────────
# to_pdf: dispatch & failure modes
# ──────────────────────────────────────────────────────────────────────────────

class TestToPdfNotFound:

    def test_raises_when_no_binary(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        with patch("docxwatermarker.pdf.shutil.which", return_value=None):
            with pytest.raises(PDFConversionError) as exc:
                to_pdf(docx)
        assert exc.value.context.get("reason") == "not_found"


class TestToPdfBinaryOverride:

    def test_explicit_binary_skips_search(self, tmp_path, monkeypatch):
        """If soffice_binary is passed, we don't even call shutil.which."""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        expected_pdf = tmp_path / "in.pdf"
        _make_fake_pdf(expected_pdf)

        with patch("docxwatermarker.pdf.shutil.which") as which, \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = to_pdf(docx, soffice_binary="/custom/path/to/soffice")

        which.assert_not_called()
        assert result == expected_pdf
        # The binary we passed was actually used in the subprocess call
        call_args = run.call_args[0][0]
        assert call_args[0] == "/custom/path/to/soffice"


class TestToPdfCommandConstruction:
    """Pin the exact shape of the subprocess call. If LibreOffice ever changes
    its CLI, these tests force us to notice."""

    def test_command_includes_required_flags(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        _make_fake_pdf(tmp_path / "in.pdf")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            to_pdf(docx)

        cmd = run.call_args[0][0]
        # Required flags
        assert "--headless" in cmd
        assert "--convert-to" in cmd
        assert "pdf" in cmd
        assert "--outdir" in cmd
        # some -env:UserInstallation argument is passed to avoid 
        # clashes with a running LibreOffice instance.
        env_args = [a for a in cmd if isinstance(a, str) and a.startswith("-env:UserInstallation=")]
        assert len(env_args) == 1, f"missing isolated profile arg, got: {cmd}"
        # The input docx is in the command
        assert str(docx) in cmd

    def test_outdir_is_output_directory(self, tmp_path, monkeypatch):
        """When output_path is explicit, --outdir is its parent."""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        out_dir = tmp_path / "subdir"
        out_dir.mkdir()
        explicit_out = out_dir / "result.pdf"

        # soffice always writes <input_stem>.pdf in outdir. The library will
        # rename it to the explicit output_path after subprocess returns.
        produced_by_soffice = out_dir / "in.pdf"
        _make_fake_pdf(produced_by_soffice)

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = to_pdf(docx, explicit_out)

        cmd = run.call_args[0][0]
        outdir_idx = cmd.index("--outdir")
        assert cmd[outdir_idx + 1] == str(out_dir)
        assert result == explicit_out

    def test_timeout_passed_to_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        _make_fake_pdf(tmp_path / "in.pdf")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            to_pdf(docx, timeout=42.0)

        # The timeout kwarg must propagate
        assert run.call_args.kwargs.get("timeout") == 42.0


class TestToPdfTimeout:

    def test_subprocess_timeout_becomes_pdf_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.side_effect = subprocess.TimeoutExpired(cmd="soffice", timeout=1.0)
            with pytest.raises(PDFConversionError) as exc:
                to_pdf(docx, timeout=1.0)

        assert exc.value.context["reason"] == "timeout"
        # Timeout value is in the context for diagnostics
        assert exc.value.context.get("timeout") == 1.0


class TestToPdfNonzeroExit:

    def test_nonzero_exit_becomes_pdf_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=77, stdout="", stderr="something went wrong"
            )
            with pytest.raises(PDFConversionError) as exc:
                to_pdf(docx)

        assert exc.value.context["reason"] == "nonzero_exit"
        assert exc.value.context["exit_code"] == 77
        assert "something went wrong" in exc.value.context["stderr"]


class TestToPdfNoOutput:

    def test_zero_exit_but_no_pdf_becomes_pdf_error(self, tmp_path, monkeypatch):
        """LibreOffice sometimes exits 0 but doesn't produce the file. We must
        catch this rather than returning a Path that doesn't exist."""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        # NOTE: we deliberately do NOT create the fake PDF here.

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            with pytest.raises(PDFConversionError) as exc:
                to_pdf(docx)

        assert exc.value.context["reason"] == "no_output"


class TestToPdfInputValidation:

    def test_missing_input_file_raises(self, tmp_path):
        with pytest.raises((FileNotFoundError, OSError, PDFConversionError)):
            to_pdf(tmp_path / "does_not_exist.docx")

    def test_accepts_str_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        _make_fake_pdf(tmp_path / "in.pdf")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = to_pdf(str(docx))  # str, not Path
        assert isinstance(result, Path)


class TestToPdfReturnValue:

    def test_default_output_next_to_input(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        _make_fake_pdf(tmp_path / "in.pdf")

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = to_pdf(docx)
        assert result == tmp_path / "in.pdf"

    def test_custom_output_path_renames_after_conversion(self, tmp_path, monkeypatch):
        """soffice writes <stem>.pdf in outdir; if user wants a different
        filename, we rename it after subprocess returns"""
        monkeypatch.delenv("DOCXWATERMARKER_SOFFICE", raising=False)
        docx = _make_dummy_docx(tmp_path / "in.docx")
        produced = tmp_path / "in.pdf"
        _make_fake_pdf(produced)
        custom_out = tmp_path / "custom_name.pdf"

        with patch("docxwatermarker.pdf.shutil.which", return_value="/usr/bin/soffice"), \
             patch("docxwatermarker.pdf.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            result = to_pdf(docx, custom_out)

        assert result == custom_out
        assert custom_out.exists()
        assert not produced.exists()  # was renamed


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

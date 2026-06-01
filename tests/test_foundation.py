"""
Foundation tests: errors, logging, invariants.

Run with:
    pytest tests/test_foundation.py -v

Or directly:
    python tests/test_foundation.py

The tests are organized in classes by module so failures point clearly to
which subsystem broke.
"""

from __future__ import annotations

import io
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make sure the src/ layout is importable when running directly.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker import (
    DocxWatermarkerError,
    ImageNotFoundError,
    MultipleImagesError,
    PDFConversionError,
    InvariantError,
    enable_debug,
    disable_debug,
    is_debug_enabled,
    configure_invariants,
    is_ensure_raising,
)
from docxwatermarker._invariants import require, ensure


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures: reset global state between tests so they don't influence each other.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state():
    """Ensure each test starts with debug OFF and ensure() in warn mode."""
    disable_debug()
    configure_invariants(raise_on_failure=False)
    yield
    disable_debug()
    configure_invariants(raise_on_failure=False)


# ──────────────────────────────────────────────────────────────────────────────
# errors.py
# ──────────────────────────────────────────────────────────────────────────────

class TestErrors:

    def test_base_error_with_no_context(self):
        e = DocxWatermarkerError("something failed")
        assert str(e) == "something failed"
        assert e.message == "something failed"
        assert e.context == {}

    def test_base_error_with_context_renders_inline(self):
        e = DocxWatermarkerError("not found", path="/tmp/x.docx", count=3)
        s = str(e)
        assert "not found" in s
        assert "path=" in s
        assert "/tmp/x.docx" in s
        assert "count=3" in s

    def test_to_dict_shape(self):
        e = ImageNotFoundError("no match", docx_path="x.docx", candidates=["a", "b"])
        d = e.to_dict()
        assert d["error"] == "ImageNotFoundError"
        assert d["message"] == "no match"
        assert d["context"]["docx_path"] == "x.docx"
        assert d["context"]["candidates"] == ["a", "b"]

    def test_subclass_hierarchy(self):
        # Every domain exception must be catchable as DocxWatermarkerError.
        for cls in (
            ImageNotFoundError,
            MultipleImagesError,
            PDFConversionError,
            InvariantError,
        ):
            assert issubclass(cls, DocxWatermarkerError)

    def test_can_be_raised_and_caught_polymorphically(self):
        with pytest.raises(DocxWatermarkerError) as exc_info:
            raise MultipleImagesError("ambiguous", matches=["a", "b"])
        assert exc_info.value.context["matches"] == ["a", "b"]

    def test_to_dict_is_json_serializable(self):
        import json
        e = PDFConversionError(
            "soffice failed", reason="timeout", exit_code=None, stderr="oops"
        )
        # Will raise if not serializable.
        s = json.dumps(e.to_dict())
        assert "PDFConversionError" in s


# ──────────────────────────────────────────────────────────────────────────────
# _logging.py
# ──────────────────────────────────────────────────────────────────────────────

class TestLogging:

    def test_debug_off_by_default(self):
        assert is_debug_enabled() is False

    def test_enable_debug_sets_flag(self):
        enable_debug()
        assert is_debug_enabled() is True

    def test_disable_debug_resets_flag(self):
        enable_debug()
        disable_debug()
        assert is_debug_enabled() is False

    def test_enable_debug_is_idempotent(self):
        # Calling twice should not attach two handlers.
        enable_debug()
        root = logging.getLogger("docxwatermarker")
        n1 = len(root.handlers)
        enable_debug()
        n2 = len(root.handlers)
        assert n1 == n2

    def test_debug_handler_writes_to_given_stream(self):
        buf = io.StringIO()
        enable_debug(stream=buf)
        logger = logging.getLogger("docxwatermarker.test")
        logger.debug("hello-from-test")
        # Force flush of any handler buffering.
        for h in logging.getLogger("docxwatermarker").handlers:
            h.flush()
        out = buf.getvalue()
        assert "hello-from-test" in out
        assert "DEBUG" in out
        assert "docxwatermarker.test" in out

    def test_null_handler_attached_by_default(self):
        # Library convention: NullHandler so 'no handlers' warning never fires.
        root = logging.getLogger("docxwatermarker")
        assert any(isinstance(h, logging.NullHandler) for h in root.handlers)

    def test_env_var_enables_debug(self):
        # Spawn a fresh interpreter with the env var set, so the import-time
        # check fires. Doing this in-process would not retrigger the module
        # initialization code.
        script = (
            "import sys; sys.path.insert(0, 'src'); "
            "import docxwatermarker; "
            "print('DEBUG=', docxwatermarker.is_debug_enabled())"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "DOCXWATERMARKER_DEBUG": "1"},
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        assert "DEBUG= True" in result.stdout

    def test_env_var_off_keeps_debug_off(self):
        script = (
            "import sys; sys.path.insert(0, 'src'); "
            "import docxwatermarker; "
            "print('DEBUG=', docxwatermarker.is_debug_enabled())"
        )
        env = {k: v for k, v in os.environ.items() if k != "DOCXWATERMARKER_DEBUG"}
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, result.stderr
        assert "DEBUG= False" in result.stdout


# ──────────────────────────────────────────────────────────────────────────────
# _invariants.py
# ──────────────────────────────────────────────────────────────────────────────

class TestRequire:
    """require() is ALWAYS active, ALWAYS raises."""

    def test_passes_when_true(self):
        require(True, "should not fire")  # no exception

    def test_raises_when_false_in_debug_off(self):
        assert is_debug_enabled() is False
        with pytest.raises(InvariantError) as exc:
            require(False, "bad input", arg="x")
        assert exc.value.context["kind"] == "require"
        assert exc.value.context["arg"] == "x"

    def test_raises_when_false_in_debug_on(self):
        enable_debug()
        with pytest.raises(InvariantError):
            require(False, "still raises in debug")

    def test_carries_context_in_to_dict(self):
        try:
            require(False, "bad", a=1, b=[2, 3])
        except InvariantError as e:
            d = e.to_dict()
            assert d["context"]["a"] == 1
            assert d["context"]["b"] == [2, 3]
            assert d["context"]["kind"] == "require"


class TestEnsureWarnMode:
    """ensure() in default mode: silent when debug off, logs warning when on."""

    def test_silent_when_debug_off(self, caplog):
        assert is_debug_enabled() is False
        with caplog.at_level(logging.DEBUG, logger="docxwatermarker"):
            ensure(False, "would fire but debug is off")
        assert not any("invariant" in r.message.lower() for r in caplog.records)

    def test_passes_silently_when_true(self, caplog):
        enable_debug()
        with caplog.at_level(logging.DEBUG, logger="docxwatermarker"):
            ensure(True, "all good")
        assert not any("invariant" in r.message.lower() for r in caplog.records)

    def test_logs_warning_when_false_in_debug(self, caplog):
        enable_debug()
        with caplog.at_level(logging.WARNING, logger="docxwatermarker"):
            ensure(False, "postcondition broke", expected=5, actual=4)
        records = [r for r in caplog.records if "invariant" in r.message.lower()]
        assert len(records) == 1
        msg = records[0].message
        assert "postcondition broke" in msg
        assert "expected=5" in msg
        assert "actual=4" in msg

    def test_does_not_raise_in_warn_mode(self):
        enable_debug()
        # Default is warn mode; should not raise.
        ensure(False, "should not raise")


class TestEnsureRaiseMode:
    """ensure() in raise mode: opt-in via configure_invariants."""

    def test_configure_sets_flag(self):
        assert is_ensure_raising() is False
        configure_invariants(raise_on_failure=True)
        assert is_ensure_raising() is True

    def test_raises_when_configured_and_debug_on(self):
        enable_debug()
        configure_invariants(raise_on_failure=True)
        with pytest.raises(InvariantError) as exc:
            ensure(False, "should raise", n=42)
        assert exc.value.context["kind"] == "ensure"
        assert exc.value.context["n"] == 42

    def test_does_not_raise_when_debug_off_even_in_raise_mode(self):
        # Debug off → ensure() is a no-op regardless of raise_on_failure.
        # This is important: production code with raise mode set must not
        # blow up just because someone forgot enable_debug().
        configure_invariants(raise_on_failure=True)
        assert is_debug_enabled() is False
        ensure(False, "should not raise, debug is off")

    def test_passes_silently_when_true(self):
        enable_debug()
        configure_invariants(raise_on_failure=True)
        ensure(True, "fine")  # no exception


# ──────────────────────────────────────────────────────────────────────────────
# Integration smoke: the three modules cooperate sensibly.
# ──────────────────────────────────────────────────────────────────────────────

class TestIntegration:

    def test_debug_workflow_end_to_end(self):
        """A realistic flow: enable debug, ensure fails, warning is logged,
        switch to raise mode, ensure raises."""
        buf = io.StringIO()
        enable_debug(stream=buf)

        # First failure: warn mode (default).
        ensure(False, "first failure", step=1)

        # Switch to raise mode.
        configure_invariants(raise_on_failure=True)
        with pytest.raises(InvariantError) as exc:
            ensure(False, "second failure", step=2)
        assert exc.value.context["step"] == 2

        for h in logging.getLogger("docxwatermarker").handlers:
            h.flush()
        out = buf.getvalue()
        assert "first failure" in out
        # The second one raised before logging (raise mode short-circuits).

    def test_caller_can_catch_everything_with_base_class(self):
        """Any library exception is catchable as DocxWatermarkerError."""
        for raise_what in [
            lambda: require(False, "x"),
            lambda: (_ for _ in ()).throw(ImageNotFoundError("a")),
            lambda: (_ for _ in ()).throw(MultipleImagesError("b", matches=[])),
            lambda: (_ for _ in ()).throw(PDFConversionError("c")),
        ]:
            with pytest.raises(DocxWatermarkerError):
                raise_what()


# ──────────────────────────────────────────────────────────────────────────────
# Direct-run entrypoint
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Allows running `python tests/test_foundation.py` without pytest CLI.
    sys.exit(pytest.main([__file__, "-v"]))

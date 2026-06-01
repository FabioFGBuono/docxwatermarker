"""
Edge-case and design-protection tests.

Companion to test_foundation.py. These tests do NOT cover the happy paths
(those live in test_foundation.py), they protect design decisions from
silent drift and check the rough edges of the API.

Run with: pytest tests/test_edge_cases.py -v
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from docxwatermarker import (
    DocxWatermarkerError,
    InvariantError,
    enable_debug,
    disable_debug,
    is_debug_enabled,
    configure_invariants,
)
from docxwatermarker._invariants import require, ensure


@pytest.fixture(autouse=True)
def _reset_state():
    disable_debug()
    configure_invariants(raise_on_failure=False)
    yield
    disable_debug()
    configure_invariants(raise_on_failure=False)


# ──────────────────────────────────────────────────────────────────────────────
# Category B — protect design decisions from silent drift
# ──────────────────────────────────────────────────────────────────────────────

class TestEnsureEvaluatesConditionAlways:
    """Documented behavior: ensure() evaluates `condition` even when debug is
    off, so callers must keep the expression cheap. This test pins that down:
    if someone "optimizes" the code to short-circuit before evaluating, this
    test breaks and forces a deliberate design discussion"""

    def test_condition_evaluated_when_debug_off(self):
        evaluations = []

        def expensive() -> bool:
            evaluations.append(1)
            return True

        assert is_debug_enabled() is False
        ensure(expensive(), "noop in production")
        # The expression was evaluated BEFORE ensure(), ensure itself can't
        # prevent that, this test makes the trade-off explicit.
        assert len(evaluations) == 1

    def test_condition_evaluated_when_debug_on(self):
        evaluations = []

        def cheap() -> bool:
            evaluations.append(1)
            return True

        enable_debug()
        ensure(cheap(), "all good")
        assert len(evaluations) == 1


class TestDebugApiEnvVarInteraction:
    """When env var was not set at import, API toggles still work normally.
    And API toggles override the initial state regardless of env var."""

    def test_api_can_enable_after_env_off(self):
        # In this process the env var was not set at import time, so debug
        # starts off. API call must still work.
        assert is_debug_enabled() is False
        enable_debug()
        assert is_debug_enabled() is True

    def test_api_can_disable_even_if_env_set(self, monkeypatch):
        # env var was set, so library is already in debug mode.
        # The API must let the user turn it off.
        enable_debug()  # mimic post-import state with env on
        assert is_debug_enabled() is True
        disable_debug()
        assert is_debug_enabled() is False


class TestEnableDisableCycle:
    """enable -> disable -> enable must work cleanly and not leave duplicate
    handlers. This is the main risk of an idempotency bug regressing."""

    def test_cycle_does_not_leak_handlers(self):
        root = logging.getLogger("docxwatermarker")
        baseline = len(root.handlers)

        enable_debug()
        after_first_enable = len(root.handlers)
        assert after_first_enable == baseline + 1

        disable_debug()
        after_disable = len(root.handlers)
        assert after_disable == baseline

        enable_debug()
        after_second_enable = len(root.handlers)
        assert after_second_enable == baseline + 1

        disable_debug()


class TestKindKwargReserved:
    """'kind' is a reserved kwarg in require()/ensure()
    because the library uses it to mark the source of the invariant
    violation. Letting callers override it would be a silent footgun."""

    def test_require_rejects_kind_kwarg_with_typeerror(self):
        with pytest.raises(TypeError, match="kind.*reserved"):
            require(True, "msg", kind="user_supplied")

    def test_require_rejects_kind_even_when_condition_false(self):
        # The kind-check must happen before the condition check, so that
        # misuse is caught regardless of whether the precondition holds.
        with pytest.raises(TypeError, match="kind.*reserved"):
            require(False, "would normally raise InvariantError", kind="x")

    def test_ensure_rejects_kind_kwarg_with_typeerror(self):
        enable_debug()
        with pytest.raises(TypeError, match="kind.*reserved"):
            ensure(False, "msg", kind="user_supplied")

    def test_ensure_rejects_kind_even_with_debug_off(self):
        # The kind-check is enforced before the debug-mode gate, so that
        # misuse is reported immediately even in production. Otherwise a
        # bug would lurk until someone turned on debug mode
        assert is_debug_enabled() is False
        with pytest.raises(TypeError, match="kind.*reserved"):
            ensure(False, "msg", kind="user_supplied")

    def test_kind_is_correctly_set_for_require(self):
        try:
            require(False, "bad")
        except InvariantError as e:
            assert e.context["kind"] == "require"

    def test_kind_is_correctly_set_for_ensure(self):
        enable_debug()
        configure_invariants(raise_on_failure=True)
        try:
            ensure(False, "bad")
        except InvariantError as e:
            assert e.context["kind"] == "ensure"


class TestEnsureWarnMessageContent:
    """The warning log emitted by ensure() in warn mode must include the
    context fields, so users can act on it without re-running with raise
    mode."""

    def test_warn_message_includes_all_context_fields(self, caplog):
        enable_debug()
        with caplog.at_level(logging.WARNING, logger="docxwatermarker"):
            ensure(False, "broken", a=1, b="two", c=[3, 4])
        records = [r for r in caplog.records if "invariant" in r.getMessage().lower()]
        assert len(records) == 1
        msg = records[0].getMessage()
        assert "a=1" in msg
        assert "b='two'" in msg
        assert "c=[3, 4]" in msg


class TestEnsureRaiseModeNoLogSpam:

    def test_raise_mode_does_not_also_log_warning(self, caplog):
        enable_debug()
        configure_invariants(raise_on_failure=True)
        with caplog.at_level(logging.WARNING, logger="docxwatermarker"):
            with pytest.raises(InvariantError):
                ensure(False, "boom", x=1)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == []


class TestConfigureInvariantsReversibility:
    """configure_invariants must be reversible"""

    def test_toggle_off_after_on(self):
        from docxwatermarker import is_ensure_raising
        assert is_ensure_raising() is False
        configure_invariants(raise_on_failure=True)
        assert is_ensure_raising() is True
        configure_invariants(raise_on_failure=False)
        assert is_ensure_raising() is False


class TestEnableDebugStreamSwitch:
    """If enable_debug is called, then disable, then enable with a different
    stream, only the second stream receives output."""

    def test_only_latest_stream_receives_output(self):
        stream_a = io.StringIO()
        stream_b = io.StringIO()

        enable_debug(stream=stream_a)
        logger = logging.getLogger("docxwatermarker.test")
        logger.debug("first")
        for h in logging.getLogger("docxwatermarker").handlers:
            h.flush()
        assert "first" in stream_a.getvalue()

        disable_debug()
        enable_debug(stream=stream_b)
        logger.debug("second")
        for h in logging.getLogger("docxwatermarker").handlers:
            h.flush()
        assert "second" in stream_b.getvalue()
        assert "second" not in stream_a.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# Category A - ergonomic edge cases that matter
# ──────────────────────────────────────────────────────────────────────────────

class TestToDictJsonSafety:
    """to_dict() must always produce JSON-serializable output"""

    def test_path_in_context_becomes_repr(self):
        e = DocxWatermarkerError("err", path=Path("/tmp/x"))
        d = e.to_dict()
        # Must not raise
        s = json.dumps(d)
        # Repr preserves type info (PosixPath('...') or WindowsPath('...'))
        assert "Path" in s

    def test_nested_path_in_list_handled(self):
        e = DocxWatermarkerError("err", paths=[Path("/a"), Path("/b")])
        d = e.to_dict()
        s = json.dumps(d)  # must not raise
        parsed = json.loads(s)
        assert len(parsed["context"]["paths"]) == 2

    def test_path_in_nested_dict_handled(self):
        e = DocxWatermarkerError("err", info={"file": Path("/x"), "n": 3})
        d = e.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["context"]["info"]["n"] == 3
        assert "Path" in parsed["context"]["info"]["file"]

    def test_tuple_becomes_list(self):
        # JSON has no tuple type... we normalize to list.
        e = DocxWatermarkerError("err", coords=(1, 2, 3))
        d = e.to_dict()
        assert d["context"]["coords"] == [1, 2, 3]
        json.dumps(d)  # serializable

    def test_non_string_dict_keys_coerced(self):
        e = DocxWatermarkerError("err", mapping={1: "a", 2: "b"})
        d = e.to_dict()
        s = json.dumps(d)
        parsed = json.loads(s)
        assert "1" in parsed["context"]["mapping"]
        assert parsed["context"]["mapping"]["1"] == "a"

    def test_primitives_pass_through_unchanged(self):
        e = DocxWatermarkerError(
            "err", n=None, b=True, i=1, f=1.5, s="x", lst=[1, 2], dct={"k": "v"}
        )
        d = e.to_dict()
        assert d["context"]["n"] is None
        assert d["context"]["b"] is True
        assert d["context"]["i"] == 1
        assert d["context"]["f"] == 1.5
        assert d["context"]["s"] == "x"
        assert d["context"]["lst"] == [1, 2]
        assert d["context"]["dct"] == {"k": "v"}

    def test_exception_object_in_context(self):
        # chaining errors with the cause inside context
        inner = ValueError("inner problem")
        e = DocxWatermarkerError("wrapped", cause=inner)
        d = e.to_dict()
        s = json.dumps(d)  # must not raise
        assert "ValueError" in s


class TestUserHandlerPreserved:
    """enable_debug() and disable_debug() must not touch handlers that the
    user attached themselves."""

    def test_user_handler_survives_enable_disable_cycle(self):
        root = logging.getLogger("docxwatermarker")
        user_handler = logging.StreamHandler(io.StringIO())
        root.addHandler(user_handler)
        try:
            enable_debug()
            assert user_handler in root.handlers
            disable_debug()
            assert user_handler in root.handlers
        finally:
            root.removeHandler(user_handler)


class TestDisableDebugWithoutEnable:
    """Calling disable_debug() without a prior enable_debug() must be a no-op, not raise"""

    def test_disable_without_enable_does_not_raise(self):
        # Fresh state from the autouse fixture
        assert is_debug_enabled() is False
        # Must not raise
        disable_debug()
        assert is_debug_enabled() is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

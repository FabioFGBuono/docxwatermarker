"""
Internal invariant checks

    require(condition, message, **context)
        Precondition. Part of the public contract: if it fails, the caller
        is using the API wrong. ALWAYS active, ALWAYS raises InvariantError.

    ensure(condition, message, **context)
        Postcondition / internal invariant. Used to verify that the library's
        own logic produced a consistent result. Active ONLY in debug mode
        (controlled by _logging.is_debug_enabled()). By default LOGS a
        warning; configurable to RAISE via configure_invariants().

Why two functions:

    require enforces the public contract, fail-fast is right and the user
    needs a clear error.

    ensure catches bugs in our own code, in production we don't want to
    crash a working pipeline just because we discovered an inconsistency
    after the fact (the document is already produced). We log a warning
    so the issue is visible without breaking the user. In dev/CI you can
    flip to raise mode to fail-fast.

The split matches the design-by-contract tradition (Eiffel's require/ensure)
and avoids the common Python anti-pattern of using `assert` for both, which
breaks under `python -O` and conflates two distinct concerns.
"""

from __future__ import annotations

from typing import Any

from docxwatermarker._logging import get_logger, is_debug_enabled
from docxwatermarker.errors import InvariantError

_logger = get_logger(__name__)

# When True, ensure() raises InvariantError on failure instead of logging.
# Configured via configure_invariants(). Default False = warn-and-continue,
# which is production-safe.
_ensure_raises: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# Spec registry (formal-specification cross-reference).
#
# Every require()/ensure() call may carry a `spec=` identifier naming the
# clause of the axiomatic specification it realizes (e.g. "I2", "P:from_bytes").
# We record each identifier the first time its check runs, so that tests can
# assert "every spec id used in the code is documented, and vice versa",
# replacing fragile line-number references in the spec document.
#
# Some spec clauses are realized WITHOUT a require/ensure (e.g. immutability
# via MappingProxyType, or a preventive raise). Those are declared statically
# in SPEC_REALIZATIONS below so the cross-reference is complete.
# ──────────────────────────────────────────────────────────────────────────────

# Spec ids observed at runtime via require()/ensure() spec= arguments.
_seen_specs: set[str] = set()


def _record_spec(spec: str) -> None:
    """Register that a check carrying `spec` was reached. Idempotent."""
    _seen_specs.add(spec)


def recorded_specs() -> frozenset[str]:
    """Return the spec ids seen so far through require()/ensure() calls.

    Note this reflects only checks that have actually executed. Tests that
    want the full set should exercise the code paths, or rely on the static
    catalogue in SPEC_REALIZATIONS for clauses realized by other means.
    """
    return frozenset(_seen_specs)


# Static catalogue: every spec clause and how the code realizes it. The
# `via` field is descriptive; `enforced_by` distinguishes runtime-checked
# clauses (a require/ensure carries the matching spec=) from those realized
# structurally. Keep this in sync with the spec document's invariant table.
# the test test_spec_crossref.py verifies the two agree.
SPEC_REALIZATIONS: dict[str, dict[str, str]] = {
    "I1": {"via": "MappingProxyType in Template.__init__", "enforced_by": "structure"},
    "I2": {"via": "ensure in Template.replace_image",       "enforced_by": "ensure"},
    "I3": {"via": "preventive FormatMismatchError",          "enforced_by": "structure"},
    "I4": {"via": "by_marker uniqueness convention",         "enforced_by": "convention"},
    "I5": {"via": "property tests in test_zipops.py",        "enforced_by": "tests"},
    "P:from_bytes":  {"via": "require in Template.from_bytes",   "enforced_by": "require"},
    "P:by_filename": {"via": "require in by_filename",          "enforced_by": "require"},
}


def configure_invariants(*, raise_on_failure: bool) -> None:
    """Set the behavior of ensure() on failure.

    Parameters
    ----------
    raise_on_failure
        If True, a failing ensure() raises InvariantError. If False, it
        emits a WARNING via logging and execution continues. Default False.

    Note: require() always raises and is not affected by this setting.
    """
    global _ensure_raises
    _ensure_raises = raise_on_failure


def is_ensure_raising() -> bool:
    """True if ensure() is currently configured to raise on failure."""
    return _ensure_raises


def require(
    condition: bool,
    message: str,
    *,
    spec: str | None = None,
    **context: Any,
) -> None:
    """Check a precondition. Always active.

    Failure indicates the caller violated the API contract. Raises
    InvariantError immediately.

    Use this for input validation that's part of the public contract:
    type/value checks on function arguments, etc.

    Parameters
    ----------
    spec
        Optional identifier tying this check to a clause in the formal
        specification (e.g. "P:from_bytes"). When given, it is recorded so
        that tooling can verify code and spec stay in sync, and it is added
        to the error context under the 'spec' key. See _spec_registry.

    The keyword 'kind' is reserved: it is always set to 'require' by this
    function to identify the source of the violation. Passing 'kind' as a
    kwarg raises TypeError.
    """
    if "kind" in context:
        raise TypeError(
            "'kind' is a reserved context key for require(); "
            "use a different name for your field"
        )
    if spec is not None:
        _record_spec(spec)
        context = {"spec": spec, **context}
    if not condition:
        raise InvariantError(message, kind="require", **context)


def ensure(
    condition: bool,
    message: str,
    *,
    spec: str | None = None,
    **context: Any,
) -> None:
    """Check a postcondition or internal invariant.

    Active only when debug mode is enabled (see _logging.enable_debug or
    the DOCXWATERMARKER_DEBUG env var). On failure, the default is to log a
    warning and continue. If configured via configure_invariants(
    raise_on_failure=True), raises InvariantError instead.

    Use this for self-checks: "after this operation, X must be true",
    "the zip should still have N entries", etc. The condition expression
    is still evaluated even in debug-off mode, keep it cheap. For
    expensive checks, gate them yourself with is_debug_enabled().

    Parameters
    ----------
    spec
        Optional identifier tying this check to a clause in the formal
        specification (e.g. "I2"). Recorded for tooling and added to the
        error/warning context. See _spec_registry

    The keyword 'kind' is reserved... it is always set to 'ensure' by this
    function. Passing 'kind' as a kwarg raises TypeError. The check is
    enforced before the debug-mode gate so callers get immediate feedback
    on misuse, regardless of whether debug is enabled. The spec is recorded
    eagerly because registration must not depend on debug mode.
    """
    if "kind" in context:
        raise TypeError(
            "'kind' is a reserved context key for ensure(); "
            "use a different name for your field"
        )

    if spec is not None:
        _record_spec(spec)
        context = {"spec": spec, **context}

    if not is_debug_enabled():
        return
    if condition:
        return

    if _ensure_raises:
        raise InvariantError(message, kind="ensure", **context)

    # Default: warn and continue. The user sees the issue but their
    # pipeline isn't broken by our paranoia.
    _logger.warning(
        "invariant violated: %s%s",
        message,
        f" [{', '.join(f'{k}={v!r}' for k, v in context.items())}]" if context else "",
    )

"""
Logging setup for docxwatermarker.

This module is INTERNAL (underscore-prefixed). The only function intended
for public use is `enable_debug()`, re-exported from the package root.

Design:

1. Every module obtains its logger via `logging.getLogger(__name__)`, which
   gives us a hierarchy. docxwatermarker, docxwatermarker.core, docxwatermarker.cli, etc.
   Callers can silence or enable individual sub-loggers as needed.

2. The root logger 'docxwatermarker' has a NullHandler attached at import time,
   so a library that imports docxwatermarker without configuring logging will
   not see any output. This is the standard library-author convention
   (see https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library).

3. Debug mode is controlled by, in order of precedence:
       a) explicit call to enable_debug()
       b) environment variable DOCXWATERMARKER_DEBUG=1
       c) default: off

   The CLI layer translates --debug to enable_debug(); enable_debug() can
   also be called directly by users embedding the library.

4. Enabling debug attaches a StreamHandler to stderr with a clear format,
   sets the root logger to DEBUG, and also flips a flag read by the
   invariants module to enable postcondition checks.
"""

from __future__ import annotations

import logging
import os
import sys

# The single root logger for the library. All sub-loggers derive from this
# via the dotted name hierarchy.
_ROOT_NAME = "docxwatermarker"
_ENV_VAR = "DOCXWATERMARKER_DEBUG"

# Internal flag mirroring debug state. Read by the invariants module to
# decide whether to evaluate ensure() checks. We keep a separate flag
# (rather than checking logger level) so invariant evaluation can be
# toggled independently of log verbosity if needed in the future.
_debug_enabled: bool = False

# Reference to the handler we attach in enable_debug(), so disable_debug()
# can remove it cleanly without touching handlers the user might have set.
_debug_handler: logging.Handler | None = None


def _install_null_handler() -> None:
    """Attach a NullHandler to the root library logger.

    Called once at import time. Prevents 'No handlers could be found' warnings
    in applications that haven't configured logging.
    """
    root = logging.getLogger(_ROOT_NAME)
    if not any(isinstance(h, logging.NullHandler) for h in root.handlers):
        root.addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the docxwatermarker namespace.

    Internal helper. Modules should call this with `__name__` so that the
    logger names reflect the module hierarchy (docxwatermarker.core, etc.).
    """
    return logging.getLogger(name)


def is_debug_enabled() -> bool:
    """True if debug mode is currently active."""
    return _debug_enabled


def enable_debug(*, stream=None) -> None:
    """Turn on debug mode.

    Effects:
      - Root logger level set to DEBUG.
      - A StreamHandler is attached to the given stream (default: sys.stderr)
        with a verbose format.
      - The internal _debug_enabled flag is set, activating ensure() checks
        in the invariants module.

    Calling multiple times is idempotent (no duplicate handler attached).
    """
    global _debug_enabled, _debug_handler

    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG)

    if _debug_handler is None:
        handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "[%(levelname)s] %(name)s: %(message)s",
            )
        )
        root.addHandler(handler)
        _debug_handler = handler

    _debug_enabled = True


def disable_debug() -> None:
    """Turn off debug mode.

    Removes the debug handler (if installed by us) and resets the level.
    Does not touch handlers attached by the user.
    """
    global _debug_enabled, _debug_handler

    root = logging.getLogger(_ROOT_NAME)
    if _debug_handler is not None:
        root.removeHandler(_debug_handler)
        _debug_handler = None
    root.setLevel(logging.WARNING)
    _debug_enabled = False


def _apply_env_var() -> None:
    """If DOCXWATERMARKER_DEBUG=1 in env, enable debug at import time."""
    val = os.environ.get(_ENV_VAR, "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        enable_debug()


# Run at import time. Order matters: null handler first (so any logging
# from the env-var path doesn't warn), then env var.
_install_null_handler()
_apply_env_var()

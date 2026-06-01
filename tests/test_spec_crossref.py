"""
Cross-reference between the code's spec= annotations and the formal
specification document.

This is the guardian that replaces fragile line-number references. Every
require()/ensure() in the code may carry a spec= identifier (e.g. "I2",
"P:from_bytes"). The same identifiers appear:

  - in _invariants.SPEC_REALIZATIONS (the static catalogue of every clause
    and how it is realized), and
  - in the invariant table of the spec document (SEMANTICS.md / SEMANTICA.md).

These tests assert the three stay in agreement, so a clause cannot be
renamed in one place without the build going red. Line numbers are no
longer referenced anywhere; the spec identifier is the durable link.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from docxwatermarker import _invariants as inv


_SRC = Path(__file__).resolve().parents[1] / "src" / "docxwatermarker"
_REPO = Path(__file__).resolve().parents[1]


def _spec_args_in_source() -> set[str]:
    """Collect every literal passed as spec= to require()/ensure() across
    the source tree, by parsing the AST (no code execution needed)."""
    found: set[str] = set()
    for py in _SRC.rglob("*.py"):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name not in ("require", "ensure"):
                continue
            for kw in node.keywords:
                if kw.arg == "spec" and isinstance(kw.value, ast.Constant):
                    found.add(kw.value.value)
    return found


def _ids_in_spec_doc(doc: Path) -> set[str]:
    """Extract invariant ids (I1..In) from the invariant table of a spec
    document. The table rows look like: | I2 (nameset preservation) | ... |"""
    ids: set[str] = set()
    for line in doc.read_text().splitlines():
        m = re.match(r"\|\s*(I\d+)\b", line)
        if m:
            ids.add(m.group(1))
    return ids


class TestSpecCrossReference:

    def test_every_code_spec_is_catalogued(self):
        """Each spec= used in the code must exist in SPEC_REALIZATIONS."""
        used = _spec_args_in_source()
        catalogue = set(inv.SPEC_REALIZATIONS)
        missing = used - catalogue
        assert not missing, (
            f"spec ids used in code but absent from SPEC_REALIZATIONS: {missing}"
        )

    def test_runtime_clauses_are_actually_annotated(self):
        """Each catalogue clause marked enforced_by require/ensure must have
        a matching spec= somewhere in the code."""
        used = _spec_args_in_source()
        for spec_id, meta in inv.SPEC_REALIZATIONS.items():
            if meta["enforced_by"] in ("require", "ensure"):
                assert spec_id in used, (
                    f"{spec_id} is catalogued as {meta['enforced_by']}-enforced "
                    f"but no require/ensure carries spec={spec_id!r}"
                )

    def test_catalogue_invariants_appear_in_spec_documents(self):
        """Every I-numbered clause in the catalogue appears in the invariant
        table of both spec documents (English and Italian)."""
        catalogue_invariants = {k for k in inv.SPEC_REALIZATIONS if re.fullmatch(r"I\d+", k)}
        for doc_name in ("SEMANTICS.md", "SEMANTICA.md"):
            doc = _REPO / doc_name
            doc_ids = _ids_in_spec_doc(doc)
            missing = catalogue_invariants - doc_ids
            assert not missing, (
                f"{doc_name} is missing invariant rows for: {missing}"
            )

    def test_spec_documents_have_no_stray_invariants(self):
        """The spec documents must not list invariant ids the catalogue
        doesn't know about (catches a clause documented but never realized)."""
        catalogue_invariants = {k for k in inv.SPEC_REALIZATIONS if re.fullmatch(r"I\d+", k)}
        for doc_name in ("SEMANTICS.md", "SEMANTICA.md"):
            doc = _REPO / doc_name
            doc_ids = _ids_in_spec_doc(doc)
            stray = doc_ids - catalogue_invariants
            assert not stray, (
                f"{doc_name} lists invariants absent from SPEC_REALIZATIONS: {stray}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# Operational-semantics cross-reference.
#
# The operational documents (OPERATIONAL.md / OPERAZIONALE.md) model the CLI as
# a transition system whose terminal configurations are the exit codes. The
# truth about those codes lives in the code. Every `return <int>` in cmd_stamp
# and cmd_inspect is a code the semantics must account for. We extract that set
# from the source by AST and check it equals the set the documents tabulate.
#
# This is the operational pendant of the spec= cross-reference above, it ties
# the operational semantics to the code as tightly as spec= ties the axiomatic
# one, so a code added or removed in one place without the other fails the
# build. Codes 2 and 130 come from main() (an unparsable command line and an
# interrupt) and are declared out of scope by the documents, so they are
# excluded here by reading only the two cmd_* functions the semantics models.
# ──────────────────────────────────────────────────────────────────────────────

# The two subcommand functions whose exit codes the operational semantics models.
_MODELLED_COMMANDS = ("cmd_stamp", "cmd_inspect")


def _exit_codes_in_source() -> set[int]:
    """Collect every integer literal returned by the modelled cmd_* functions
    in cli.py, by parsing the AST. These are the CLI's terminal exit codes."""
    cli = _SRC / "cli.py"
    tree = ast.parse(cli.read_text(), filename=str(cli))
    codes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in _MODELLED_COMMANDS:
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Return)
                and isinstance(sub.value, ast.Constant)
                and isinstance(sub.value.value, int)
                and not isinstance(sub.value.value, bool)
            ):
                codes.add(sub.value.value)
    return codes


def _exit_codes_in_operational_doc(doc: Path) -> set[int]:
    """Extract the exit codes tabulated in an operational document. The
    'exit codes together' table has rows of the form: | 3 | ... |"""
    codes: set[int] = set()
    for line in doc.read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|", line)
        if m:
            codes.add(int(m.group(1)))
    return codes


class TestOperationalCrossReference:

    def test_code_exit_codes_match_documents(self):
        """The exit codes the CLI can return from its modelled subcommands
        must be exactly those the operational documents tabulate."""
        from_code = _exit_codes_in_source()
        for doc_name in ("OPERATIONAL.md", "OPERAZIONALE.md"):
            from_doc = _exit_codes_in_operational_doc(_REPO / doc_name)
            assert from_code == from_doc, (
                f"exit codes disagree between cli.py {sorted(from_code)} and "
                f"{doc_name} {sorted(from_doc)}: "
                f"in code only {sorted(from_code - from_doc)}, "
                f"in doc only {sorted(from_doc - from_code)}"
            )

    def test_both_operational_documents_agree(self):
        """The English and Italian operational documents must tabulate the
        same set of exit codes."""
        en = _exit_codes_in_operational_doc(_REPO / "OPERATIONAL.md")
        it = _exit_codes_in_operational_doc(_REPO / "OPERAZIONALE.md")
        assert en == it, (
            f"OPERATIONAL.md {sorted(en)} and OPERAZIONALE.md {sorted(it)} "
            f"tabulate different exit codes"
        )

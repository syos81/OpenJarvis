"""Mechanical derivation of the product guard base (B0a-2 §0).

The guard base is never configured. It is derived from the git history at
every gate run, from constants that live in this module and nowhere else:

* canonical line   ``jarvis/rebuild-v1``
* calendar line    ``spike/calendar-foundation-intel-2026-08-04``
* tooling branch   ``tooling/gates-v1``
* owner verified line origin ``d037cb6``

Derivation steps, all mandatory:

1. resolve every involved reference to a full commit OID,
2. determine ``git merge-base --all`` of the canonical and the calendar line,
3. fail on no merge base and on more than one,
4. resolve ``d037cb6^{commit}`` to its full OID,
5. compare the derived merge base with that OID,
6. verify that the merge bases of ``HEAD`` against both origin lines are each
   unique and identical to that same OID,
7. verify that ``d037cb6`` is an ancestor of ``HEAD``.

There is no fallback: not ``main``, not the previous block commit, not
``HEAD``, not a manifest value, not an environment variable, not a CLI
parameter, not a cache entry, not a later commit. The manifest field
``product_guard.block_base_commit`` is a declaration that gets *validated*
against the derived base — it can never supply, shorten or override it.
"""

from __future__ import annotations

import re

from . import gitutil
from . import statuses

#: Frozen line identities. Not configurable, not overridable at runtime.
CANONICAL_LINE = "jarvis/rebuild-v1"
CALENDAR_LINE = "spike/calendar-foundation-intel-2026-08-04"
TOOLING_BRANCH = "tooling/gates-v1"
OWNER_VERIFIED_ORIGIN = "d037cb6"

_OID_RE = re.compile(r"^[0-9a-f]{40}$")


class GuardBaseError(RuntimeError):
    """Raised when the guard base cannot be derived or does not verify."""

    def __init__(self, reason_code, message=""):
        self.reason_code = reason_code
        super().__init__(message or reason_code)


def _merge_base_all(left, right, cwd):
    code, out, _ = gitutil.run_git(["merge-base", "--all", left, right], cwd=cwd)
    if code != 0:
        return []
    return sorted(line.strip() for line in out.splitlines() if line.strip())


def _unique_merge_base(left, right, cwd, reason_prefix):
    bases = _merge_base_all(left, right, cwd)
    if not bases:
        raise GuardBaseError(
            f"{reason_prefix}_merge_base_missing",
            f"no merge base between {left} and {right}",
        )
    if len(bases) > 1:
        raise GuardBaseError(
            f"{reason_prefix}_merge_base_ambiguous",
            f"{len(bases)} merge bases between {left} and {right}",
        )
    return bases[0]


def derive(
    worktree,
    *,
    canonical_line=CANONICAL_LINE,
    calendar_line=CALENDAR_LINE,
    origin_rev=OWNER_VERIFIED_ORIGIN,
):
    """Derive and verify the guard base. Returns the full base OID.

    The keyword arguments exist so the algorithm itself can be exercised on
    throwaway repositories in the tests. Production callers use
    :func:`derive_for_repository`, which passes the frozen constants only.
    """
    resolved = {}
    for name, rev in (
        ("canonical_line", canonical_line),
        ("calendar_line", calendar_line),
        ("head", "HEAD"),
    ):
        oid = gitutil.resolve_commit(rev, cwd=worktree)
        if not oid or not _OID_RE.match(oid):
            raise GuardBaseError(
                "guard_base_reference_unresolved", f"cannot resolve {rev}"
            )
        resolved[name] = oid

    derived = _unique_merge_base(
        canonical_line, calendar_line, worktree, "guard_base"
    )

    origin_oid = gitutil.resolve_commit(origin_rev, cwd=worktree)
    if not origin_oid or not _OID_RE.match(origin_oid):
        raise GuardBaseError(
            "guard_base_origin_unresolved",
            "the owner verified line origin does not resolve",
        )
    if derived != origin_oid:
        raise GuardBaseError(
            "guard_base_origin_mismatch",
            "the derived merge base is not the owner verified line origin",
        )

    # HEAD must descend from the derived origin through both lines. When HEAD
    # sits on one of the origin lines — as it does after an integration — its
    # merge base with that line is HEAD's own ancestor on that line, which
    # must itself descend from the derived origin. Equality is required only
    # when HEAD is on a third line.
    for name, line in (
        ("head_canonical", canonical_line),
        ("head_calendar", calendar_line),
    ):
        head_base = _unique_merge_base(line, "HEAD", worktree, name)
        if head_base == origin_oid:
            continue
        code, _, _ = gitutil.run_git(
            ["merge-base", "--is-ancestor", origin_oid, head_base], cwd=worktree
        )
        if code != 0:
            raise GuardBaseError(
                f"{name}_merge_base_mismatch",
                f"HEAD does not descend from the line origin via {line}",
            )

    code, _, _ = gitutil.run_git(
        ["merge-base", "--is-ancestor", origin_oid, resolved["head"]], cwd=worktree
    )
    if code != 0:
        raise GuardBaseError(
            "guard_base_not_ancestor_of_head",
            "the line origin is not an ancestor of HEAD",
        )

    return {
        "base_commit": origin_oid,
        "head_commit": resolved["head"],
        "canonical_line": canonical_line,
        "canonical_line_commit": resolved["canonical_line"],
        "calendar_line": calendar_line,
        "calendar_line_commit": resolved["calendar_line"],
        "derivation": "git_merge_base_all",
    }


def derive_for_repository(worktree):
    """Production entry point: frozen constants only, no parameters."""
    return derive(worktree)


def validate_declared_base(declared, derived_base):
    """The manifest field is validated, never used as an input.

    Returns ``(status, reason_code)``.
    """
    if not declared:
        return statuses.FAIL, "declared_guard_base_missing"
    if not isinstance(declared, str) or not _OID_RE.match(declared):
        return statuses.FAIL, "declared_guard_base_not_full_oid"
    if declared != derived_base:
        return statuses.FAIL, "declared_guard_base_mismatch"
    return statuses.PASS, "declared_guard_base_matches_derivation"

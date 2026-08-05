"""The five binding gate results, their aggregation and their exit codes.

Only these five values exist. Free text never replaces or reinterprets them;
the enum in the structured report is always authoritative.
"""

from __future__ import annotations

PASS = "pass"
PASS_WITH_BASELINE = "pass_with_baseline"
FAIL = "fail"
BLOCKED = "blocked"
NOT_APPLICABLE = "not_applicable"

#: Deterministic order, used for stable serialisation and for tests.
ALL_STATUSES = (PASS, PASS_WITH_BASELINE, FAIL, BLOCKED, NOT_APPLICABLE)

#: Aggregation precedence: lower index wins.
_PRECEDENCE = (FAIL, BLOCKED, PASS_WITH_BASELINE, PASS, NOT_APPLICABLE)

# Documented, stable exit codes.
#
# ``pass``/``pass_with_baseline``/``not_applicable`` all exit 0 so shell
# automation sees a non-failed run; they stay distinguishable through the
# ``status`` field of the machine readable report, which is authoritative.
# ``fail`` and ``blocked`` have different non-zero exit codes.
EXIT_OK = 0
EXIT_FAIL = 20
EXIT_BLOCKED = 30
EXIT_USAGE = 64
EXIT_INTERNAL = 70

EXIT_BY_STATUS = {
    PASS: EXIT_OK,
    PASS_WITH_BASELINE: EXIT_OK,
    NOT_APPLICABLE: EXIT_OK,
    FAIL: EXIT_FAIL,
    BLOCKED: EXIT_BLOCKED,
}


class GateStatusError(ValueError):
    """Raised when a value outside the five binding results is used."""


def validate(status: str) -> str:
    if status not in ALL_STATUSES:
        raise GateStatusError(f"unknown gate status: {status!r}")
    return status


def exit_code(status: str) -> int:
    return EXIT_BY_STATUS[validate(status)]


def aggregate(statuses) -> str:
    """Aggregate check results into exactly one overall result.

    An empty checklist is never a success: it aggregates to ``fail``.
    """
    materialised = [validate(s) for s in statuses]
    if not materialised:
        return FAIL
    present = set(materialised)
    for candidate in _PRECEDENCE:
        if candidate in present:
            return candidate
    raise GateStatusError("unreachable: no status matched precedence")


def aggregate_module_final(statuses) -> str:
    """Aggregate the closing phase.

    ``module-final`` must never end as ``not_applicable``: a completely
    non-applicable closing phase is a configuration error, therefore ``fail``.
    """
    result = aggregate(statuses)
    if result == NOT_APPLICABLE:
        return FAIL
    return result

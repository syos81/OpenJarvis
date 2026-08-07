"""Rule R10 — an aggregation over an empty set never reports ``pass``.

A check that walks a set and reports a problem for every bad element says
nothing at all when the set is empty. It reports no problems, and no problems
reads as success. The failure mode is invisible in exactly the way a passing
test that tests nothing is invisible: the report of a vacuous run and the
report of a clean run are byte identical.

There is one honest exception, and it is narrow: when *emptiness itself* is the
property being checked, and that expectation was derived independently of the
walk. "This phase declares no raw logs, therefore none are verified" is a
statement about the phase. "I verified nothing and found nothing wrong" is not.

The distinction is mechanical here, and it is the whole module. A caller
supplies two numbers from two different places:

``derived_expected``
    how many elements the set *should* have, established without walking it —
    from a manifest, from a declaration, from a record written earlier.
``examined``
    how many elements the walk actually looked at.

Expected zero and examined zero is the exception: the emptiness was predicted,
and finding it is a result. Expected more than zero and examined zero is the
defect: nothing was established, and the honest outcome is a non evidence
state, never ``pass``.

That state is ``blocked``. It is not a new enum value — the five binding
results stay five — and it is the one that already means *a precondition is
missing*. It carries its own reason code so it can never be confused with
another cause of ``blocked``, and because ``blocked`` outranks ``pass`` in the
aggregation precedence it cannot be absorbed into a green phase.
"""

from __future__ import annotations

from . import statuses

#: A walk that established nothing. Never part of a green result.
AGGREGATION_SET_EMPTY = "aggregation_set_empty"

#: The narrow exception: the emptiness was predicted and is the result.
DERIVED_EMPTY_SET = "derived_empty_set"

#: The ordinary case.
AGGREGATED = "aggregated"


class EmptySetError(ValueError):
    """Raised when the rule is applied to values that cannot bear it."""


def verdict(examined, derived_expected):
    """Rule R10 for one aggregation. Returns ``(status, reason_code)``.

    ``derived_expected`` must come from somewhere other than the walk itself.
    Passing the length of the walked collection for both arguments would make
    the rule vacuous, so a caller that has no independent expectation has to
    say so by using :func:`require_non_empty` instead.
    """
    examined = int(examined)
    derived_expected = int(derived_expected)
    if examined < 0 or derived_expected < 0:
        raise EmptySetError("counts must not be negative")
    if derived_expected == 0:
        if examined == 0:
            # The exception, and the only one. The emptiness was predicted
            # independently, so finding it is a result rather than an absence
            # of one.
            return statuses.PASS, DERIVED_EMPTY_SET
        # More was found than was predicted to exist. That is not this rule's
        # subject, but it is certainly not a clean aggregation either.
        raise EmptySetError("examined more elements than were derived to exist")
    if examined == 0:
        return statuses.BLOCKED, AGGREGATION_SET_EMPTY
    return statuses.PASS, AGGREGATED


def require_non_empty(examined):
    """For a set whose emptiness can never be the checked property.

    A closing phase with no phases to aggregate, for instance: there is no
    reading of that under which emptiness is the result.
    """
    if int(examined) <= 0:
        return statuses.BLOCKED, AGGREGATION_SET_EMPTY
    return statuses.PASS, AGGREGATED


def worse(current, candidate):
    """Keep the stricter of two statuses, using the binding precedence."""
    return statuses.aggregate([current, candidate])

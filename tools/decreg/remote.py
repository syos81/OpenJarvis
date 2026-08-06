"""Freshness and fast-forward rules for the canonical governance ref.

The decision logic is separated from the git invocations on purpose. Every
rule below is a pure function over an observed remote and local state, so the
full matrix — stale local ref, concurrent remote progress, missing ref,
unverifiable ref, non fast-forward — is testable without pushing anything.

What this module does **not** claim: it does not enforce anything on the
remote. A personal remote has no demonstrated server side ref protection.
The rules here run locally, before a push is even offered; the push itself is
an owner action.
"""

from __future__ import annotations

import re

_OID_RE = re.compile(r"^[0-9a-f]{40}$")

#: Machine readable outcomes. ``READY`` is the only one that permits a push.
READY = "ready"
REMOTE_REF_MISSING = "remote_ref_missing"
REMOTE_OID_UNVERIFIABLE = "remote_oid_unverifiable"
LOCAL_REF_MISSING = "local_ref_missing"
LOCAL_REF_STALE = "local_ref_stale"
REMOTE_ADVANCED = "remote_advanced_concurrently"
NOT_FAST_FORWARD = "not_a_fast_forward"
DIVERGED = "diverged"
NO_CHANGE = "no_change"


class RemoteState:
    """What was actually observed, never what was assumed."""

    __slots__ = ("remote_oid", "local_oid", "base_oid", "is_ancestor")

    def __init__(self, remote_oid, local_oid, base_oid, is_ancestor):
        self.remote_oid = remote_oid
        self.local_oid = local_oid
        #: the remote tip the local work was built on
        self.base_oid = base_oid
        #: whether remote_oid is an ancestor of local_oid
        self.is_ancestor = is_ancestor


def classify_initial(state):
    """Rule for creating the ref for the first time."""
    if state.remote_oid is not None:
        return REMOTE_ADVANCED
    if state.local_oid is None:
        return LOCAL_REF_MISSING
    return READY


def classify_update(state):
    """Rule for advancing an existing ref.

    A push is only offered when the observed remote tip is exactly the base
    the local work was built on, and the local tip really descends from it.
    """
    if state.remote_oid is None:
        return REMOTE_REF_MISSING
    if not _OID_RE.match(str(state.remote_oid)):
        return REMOTE_OID_UNVERIFIABLE
    if state.local_oid is None:
        return LOCAL_REF_MISSING
    if not _OID_RE.match(str(state.local_oid)):
        return LOCAL_REF_MISSING
    if state.base_oid is None or not _OID_RE.match(str(state.base_oid)):
        return LOCAL_REF_STALE
    if state.remote_oid != state.base_oid:
        # Somebody else moved the ref while this work was being prepared.
        return REMOTE_ADVANCED
    if state.remote_oid == state.local_oid:
        return NO_CHANGE
    if not state.is_ancestor:
        return NOT_FAST_FORWARD if state.base_oid else DIVERGED
    return READY


def push_command(remote, ref, *, local_ref=None):
    """The exact owner push command. Never a force variant."""
    source = local_ref or ref
    return f"git push {remote} {source}:{ref}"


def describe(outcome):
    """Short, non-overstated sentence for an outcome."""
    return {
        READY: "local state is a fast forward successor of the observed remote tip",
        REMOTE_REF_MISSING: "the remote ref does not exist yet",
        REMOTE_OID_UNVERIFIABLE: "the remote object id could not be verified",
        LOCAL_REF_MISSING: "the local ref does not exist",
        LOCAL_REF_STALE: "the local work was not built on a verified remote tip",
        REMOTE_ADVANCED: "the remote ref advanced while this work was prepared",
        NOT_FAST_FORWARD: "the local tip does not descend from the remote tip",
        DIVERGED: "local and remote histories diverged",
        NO_CHANGE: "there is nothing to push",
    }.get(outcome, outcome)

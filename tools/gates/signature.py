"""Versioned, structural cause signatures.

A baseline may only excuse a candidate failure when both sides fail for the
*same structural reason*. A raw log hash, an exit code, a substring match or a
textual claim are explicitly not sufficient, so this module derives the cause
from structured elements only:

block/check identity, runner and parser kind, failure class, normalised
failure ids, normalised diagnostic codes, normalised stack frames, and the
number and category of failures — under a versioned signature schema.

Everything is normalised before hashing: absolute paths, user names,
timestamps, temporary names, UUIDs, process ids, addresses, run order noise
and any other personal content. If no reliable structural cause can be built,
the functions here return ``None`` and the baseline must not excuse anything.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import CAUSE_SIGNATURE_VERSION
from . import sanitize

FAILING_OUTCOMES = ("failed", "error")

_LINE_SUFFIX_RE = re.compile(r":\d+(?=\b|$)")
_ORDER_NOISE_RE = re.compile(r"\[(?:\d+|case_\d+)\]")


class CauseSignatureError(ValueError):
    """Raised when a structured failure description is malformed."""


def normalize_token(token: str) -> str:
    """Normalise a single structural token (test id, code, frame)."""
    text = sanitize.normalize_text(str(token))
    text = _LINE_SUFFIX_RE.sub(":<line>", text)
    text = _ORDER_NOISE_RE.sub("[<n>]", text)
    text = " ".join(text.split())
    return text


def _normalised_failures(failures):
    normalised = []
    for failure in failures:
        if not isinstance(failure, dict):
            raise CauseSignatureError("failure entries must be objects")
        entry = {
            "id": normalize_token(failure.get("id", "")),
            "category": normalize_token(failure.get("category", "unknown")),
            "class": normalize_token(failure.get("class", "")),
            "code": normalize_token(failure.get("code", "")),
            "frames": sorted(
                normalize_token(frame) for frame in failure.get("frames", [])
            ),
        }
        if not entry["id"] and not entry["class"] and not entry["code"]:
            # No structural handle at all — refuse rather than guess.
            raise CauseSignatureError("failure without structural identity")
        normalised.append(entry)
    normalised.sort(key=lambda item: json.dumps(item, sort_keys=True))
    return normalised


def build_cause_signature(
    *, block_id, check_id, runner_kind, parser, structured
):
    """Build a versioned structural signature, or ``None`` if impossible."""
    if not isinstance(structured, dict):
        return None
    outcome = structured.get("outcome")
    if outcome not in FAILING_OUTCOMES:
        # Passed, timed out or otherwise structurally opaque.
        return None
    if structured.get("structural") is False:
        # Exit code only, missing report, unreadable output: no reliable cause.
        return None
    failures = structured.get("failures") or []
    diagnostics = structured.get("diagnostics") or []
    if not failures and not diagnostics:
        return None
    try:
        normalised_failures = _normalised_failures(failures)
    except CauseSignatureError:
        return None

    categories = sorted(
        {failure["category"] for failure in normalised_failures}
    )
    classes = sorted(
        {failure["class"] for failure in normalised_failures if failure["class"]}
    )
    elements = {
        "block_id": normalize_token(block_id),
        "check_id": normalize_token(check_id),
        "runner_kind": normalize_token(runner_kind),
        "parser": normalize_token(parser),
        "outcome": outcome,
        "failure_count": len(normalised_failures),
        "failure_categories": categories,
        "failure_classes": classes,
        "failures": normalised_failures,
        "diagnostics": sorted(
            normalize_token(diagnostic) for diagnostic in diagnostics
        ),
    }
    sanitize.assert_clean(elements, "$cause_signature")
    payload = {
        "signature_version": CAUSE_SIGNATURE_VERSION,
        "elements": elements,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    payload["digest"] = digest
    return payload


def compare(candidate, baseline):
    """Compare two signatures. Returns ``(is_same, reason_code)``."""
    if candidate is None or baseline is None:
        return False, "cause_signature_unavailable"
    if candidate.get("signature_version") != baseline.get("signature_version"):
        return False, "cause_signature_version_mismatch"
    candidate_elements = candidate.get("elements", {})
    baseline_elements = baseline.get("elements", {})
    if candidate_elements.get("failure_count", -1) > baseline_elements.get(
        "failure_count", -1
    ):
        return False, "baseline_additional_candidate_failures"
    if set(candidate_elements.get("failure_categories", [])) - set(
        baseline_elements.get("failure_categories", [])
    ):
        return False, "baseline_new_failure_category"
    if candidate.get("digest") != baseline.get("digest"):
        return False, "baseline_new_cause"
    return True, "baseline_match_structural"

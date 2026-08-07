"""Authority binding model of the codified decisions (B0g).

One decision has exactly one authoritative place: its DEC document. Every
other carrier of the same subject is either ``derived_enforcement`` (a
machine-read artifact that cites the DEC id and is validated against its
reader) or ``reference_only`` (prose that cites the DEC id and carries no
operative full text). The validator proves this mechanically:

* model well-formedness — roles closed, aliases and DEC ids unique, every
  decision names exactly one authoritative document;
* the authoritative document exists, its frontmatter binds DEC id, alias
  and status, and the id is structurally allocated in the register table;
* every carrier exists and carries the DEC id marker; derived enforcement
  additionally declares what validates it;
* the fragment screen — per decision at least one operative sentence that
  provably stands in the authoritative document and in **no** scanned
  carrier file. The screen is non-vacuous: an empty scan set and a
  fragment missing from its own document are both findings (R10).

The validator returns findings and never raises on content problems;
``load_model``/``load_assignment`` are the R4 loader bindings and refuse
structurally unknown input loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

CARRIER_ROLES = ("derived_enforcement", "reference_only")
MODEL_KEYS = {
    "schema_version", "kind", "statement", "register_ref",
    "register_row_file", "roles", "fragment_scan", "decisions",
}
DECISION_KEYS = {
    "alias", "dec_id", "authoritative_path", "carriers",
    "forbidden_fragments",
}
CARRIER_KEYS = {"path", "role", "validation"}
SCAN_KEYS = {"roots", "exempt_paths", "exempt_with_reason"}
ASSIGNMENT_KEYS = {
    "schema_version", "kind", "statement", "stage", "register_ref",
    "expected_remote_oid", "expected_events", "genesis_events",
    "dec_ids", "normative_commit",
}
STAGES = ("reserved", "assigned")


class AuthorityError(ValueError):
    """A structurally unacceptable model or assignment record."""


def _reject(condition, message):
    if condition:
        raise AuthorityError(message)


def load_model(path):
    """R4 loader of the authority model: rejects unknown structure."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    _reject(not isinstance(document, dict), "model must be an object")
    _reject(document.get("schema_version") != 1, "unknown schema_version")
    _reject(document.get("kind") != "decision_authority_model", "unknown kind")
    unknown = set(document) - MODEL_KEYS
    _reject(bool(unknown), f"unknown model fields: {sorted(unknown)}")
    _reject(
        tuple(document.get("roles", ())) !=
        ("authoritative",) + CARRIER_ROLES,
        "roles must list authoritative, derived_enforcement, reference_only",
    )
    scan = document.get("fragment_scan")
    _reject(not isinstance(scan, dict), "fragment_scan must be an object")
    _reject(
        set(scan) != SCAN_KEYS,
        "fragment_scan must carry exactly roots, exempt_paths and "
        "exempt_with_reason",
    )
    _reject(not scan.get("roots"), "fragment_scan.roots must be non-empty")
    decisions = document.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        # An absent or empty decision list must never load: every walk
        # over it downstream would otherwise be vacuous (R10).
        raise AuthorityError("decisions must be a non-empty list")
    for decision in decisions:
        _reject(not isinstance(decision, dict), "decision must be an object")
        _reject(
            set(decision) != DECISION_KEYS,
            "every decision carries exactly alias, dec_id, "
            "authoritative_path, carriers and forbidden_fragments",
        )
        for carrier in decision["carriers"]:
            _reject(not isinstance(carrier, dict), "carrier must be an object")
            _reject(
                bool(set(carrier) - CARRIER_KEYS),
                "unknown carrier fields",
            )
    return document


def load_assignment(path):
    """R4 loader of the assignment evidence record."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    _reject(not isinstance(document, dict), "record must be an object")
    _reject(document.get("schema_version") != 1, "unknown schema_version")
    _reject(document.get("kind") != "b0g_assignment_record", "unknown kind")
    unknown = set(document) - ASSIGNMENT_KEYS
    _reject(bool(unknown), f"unknown record fields: {sorted(unknown)}")
    _reject(document.get("stage") not in STAGES, "unknown stage")
    _reject(
        not isinstance(document.get("dec_ids"), list)
        or not document["dec_ids"],
        "dec_ids must be a non-empty list",
    )
    if document["stage"] == "assigned":
        commit = document.get("normative_commit") or ""
        _reject(
            len(commit) != 40,
            "an assigned record must bind the full normative commit oid",
        )
    else:
        _reject(
            document.get("normative_commit") is not None,
            "a reserved record must not carry a normative commit",
        )
    return document


def frontmatter(text):
    """The leading ``--- key: value ---`` block of a DEC document."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def _scan_files(root, scan):
    exempt = tuple(scan["exempt_paths"]) + tuple(
        entry["path"] for entry in scan["exempt_with_reason"]
    )
    collected = []
    for declared in scan["roots"]:
        base = root / declared
        candidates = (
            [base] if base.is_file()
            else sorted(
                candidate for suffix in ("*.json", "*.md")
                for candidate in base.rglob(suffix)
            )
        )
        for candidate in candidates:
            relative = candidate.relative_to(root).as_posix()
            if any(
                relative == item or relative.startswith(item.rstrip("/") + "/")
                for item in exempt
            ):
                continue
            collected.append(relative)
    return collected


def validate(model, root, register_ids):
    """All findings of the authority model against the working tree."""
    root = Path(root)
    findings = []

    def finding(code, subject, detail=""):
        findings.append(
            {"code": code, "subject": subject, "detail": str(detail)}
        )

    for entry in model["fragment_scan"]["exempt_with_reason"]:
        if not str(entry.get("reason", "")).strip():
            finding("exemption_without_reason", entry.get("path", "?"))
        if not (root / entry.get("path", "")).exists():
            finding("exempt_path_missing", entry.get("path", "?"))

    aliases, dec_ids = {}, {}
    for decision in model["decisions"]:
        alias = decision.get("alias", "")
        dec_id = decision.get("dec_id", "")
        subject = alias or dec_id or "?"
        if not alias:
            finding("alias_missing", subject)
        if not dec_id:
            finding("dec_id_missing", subject)
            continue
        if alias in aliases:
            finding("alias_duplicated", alias)
        aliases[alias] = dec_id
        if dec_id in dec_ids:
            finding("dec_id_bound_twice", dec_id, dec_ids[dec_id])
        dec_ids[dec_id] = alias

        authoritative = decision.get("authoritative_path", "")
        extra_authoritative = [
            carrier.get("path", "?")
            for carrier in decision["carriers"]
            if carrier.get("role") not in CARRIER_ROLES
        ]
        for path in extra_authoritative:
            finding("second_authoritative_carrier", dec_id, path)
        if not authoritative:
            finding("authoritative_missing", dec_id)
            continue

        document_path = root / authoritative
        if not document_path.is_file():
            finding("authoritative_document_missing", dec_id, authoritative)
            continue
        text = document_path.read_text(encoding="utf-8")
        front = frontmatter(text)
        if front.get("DEC-ID") != dec_id:
            finding(
                "frontmatter_dec_id_mismatch", dec_id,
                front.get("DEC-ID", "absent"),
            )
        if front.get("Regel-Alias", "").lower() != alias.lower():
            finding(
                "frontmatter_alias_mismatch", dec_id,
                front.get("Regel-Alias", "absent"),
            )
        if front.get("Status") != "accepted":
            finding("frontmatter_status_not_accepted", dec_id)
        if dec_id not in register_ids:
            finding("register_row_missing", dec_id)

        for carrier in decision["carriers"]:
            path = carrier.get("path", "")
            role = carrier.get("role", "")
            carrier_path = root / path
            if role not in CARRIER_ROLES:
                continue
            if not carrier_path.is_file():
                finding("carrier_missing", dec_id, path)
                continue
            carrier_text = carrier_path.read_text(encoding="utf-8")
            if dec_id not in carrier_text:
                finding("carrier_without_marker", dec_id, path)
            if role == "derived_enforcement":
                if not str(carrier.get("validation", "")).strip():
                    finding("enforcement_without_validation", dec_id, path)

        fragments = decision["forbidden_fragments"]
        if not fragments:
            finding("fragments_missing", dec_id)
        for fragment in fragments:
            if fragment not in text:
                finding("fragment_not_in_authoritative", dec_id, fragment)

    scanned = _scan_files(root, model["fragment_scan"])
    if not scanned:
        findings.append({
            "code": "scan_set_empty", "subject": "fragment_scan",
            "detail": "an empty scan proves nothing (R10)",
        })
    for relative in scanned:
        content = (root / relative).read_text(encoding="utf-8", errors="replace")
        for decision in model["decisions"]:
            for fragment in decision["forbidden_fragments"]:
                if fragment in content:
                    findings.append({
                        "code": "operative_text_outside_authority",
                        "subject": decision.get("dec_id", "?"),
                        "detail": f"{relative}: {fragment[:60]}",
                    })
    return findings, {"decisions": len(model["decisions"]), "scanned": len(scanned)}

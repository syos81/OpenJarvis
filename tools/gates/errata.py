"""Reference resolution against frozen documents, with explicit errata.

A frozen document is never edited. When it cites a reference that does not
exist, the citation stays exactly as it is and an erratum resolves it.

Resolution is deliberately narrow. A reference resolves if and only if:

* it resolves **directly** — the cited document exists and carries the cited
  wording, or
* **exactly one** explicit erratum covers it, that erratum is itself valid,
  and every replacement anchor resolves to a file that really carries the
  quoted wording.

There is no fuzzy matching, no silent substitution, no general alias list and
no chaining: an erratum may not point at a reference that is itself only
resolvable through another erratum. Two errata for the same reference are an
error, not a choice.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ERRATA_PATH = "config/governance/baseline-errata.json"

ERRATUM_FIELDS = (
    "affected_document",
    "affected_document_sha256",
    "citing_section",
    "erratum_id",
    "invalid_reference",
    "reason",
    "recorded_at_utc",
    "replacement_anchors",
    "source_commit",
)
ANCHOR_FIELDS = ("path", "quote_anchor", "section")

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class Resolution:
    """Outcome of resolving one reference."""

    __slots__ = ("resolved", "code", "via", "erratum_id", "anchors")

    def __init__(self, resolved, code, via="", erratum_id="", anchors=()):
        self.resolved = resolved
        self.code = code
        self.via = via
        self.erratum_id = erratum_id
        self.anchors = list(anchors)


#: Top level shape of the errata document. Rule R4: this is the accepting
#: reader, and it is effective before any field it does not know can appear.
DOCUMENT_FIELDS = ("errata", "kind", "schema_version", "statement")
DOCUMENT_KIND = "frozen_document_errata"
SCHEMA_VERSION = 1


class ErrataDocumentError(ValueError):
    """Raised with a machine readable code for an unusable errata document."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def load_document(root, path=ERRATA_PATH):
    """Load and fully validate the errata document envelope.

    Raises :class:`ErrataDocumentError`. Every erratum is validated too, so
    a document that parses but carries an unsound erratum is rejected here
    rather than at the point of use.
    """
    target = Path(root) / path
    if not target.is_file():
        raise ErrataDocumentError("errata_document_missing", str(path))
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ErrataDocumentError("errata_document_not_json", str(exc)[:80]) from exc
    if not isinstance(document, dict):
        raise ErrataDocumentError("errata_document_not_an_object")
    missing = sorted(set(DOCUMENT_FIELDS) - set(document))
    if missing:
        raise ErrataDocumentError("errata_document_missing_field", ",".join(missing))
    unknown = sorted(set(document) - set(DOCUMENT_FIELDS))
    if unknown:
        raise ErrataDocumentError("errata_document_unknown_field", ",".join(unknown))
    if document["kind"] != DOCUMENT_KIND:
        raise ErrataDocumentError("errata_document_kind_unexpected", str(document["kind"]))
    if document["schema_version"] != SCHEMA_VERSION:
        raise ErrataDocumentError("errata_document_schema_unsupported")
    if not str(document["statement"]).strip():
        raise ErrataDocumentError("errata_document_statement_missing")
    entries = document["errata"]
    if not isinstance(entries, list):
        raise ErrataDocumentError("errata_document_entries_not_a_list")
    identifiers = set()
    references = set()
    for entry in entries:
        code = validate_erratum(root, entry)
        if code:
            raise ErrataDocumentError(code, str(entry.get("erratum_id", "")) if isinstance(entry, dict) else "")
        if entry["erratum_id"] in identifiers:
            raise ErrataDocumentError("erratum_id_duplicated", entry["erratum_id"])
        identifiers.add(entry["erratum_id"])
        if entry["invalid_reference"] in references:
            # Two errata for the same reference are an error, not a choice.
            raise ErrataDocumentError("ambiguous_erratum", entry["invalid_reference"])
        references.add(entry["invalid_reference"])
    return document


def load_errata(root, path=ERRATA_PATH):
    """Load the errata document. Returns ``[]`` when there is none."""
    target = Path(root) / path
    if not target.is_file():
        return []
    document = json.loads(target.read_text(encoding="utf-8"))
    return list(document.get("errata", []))


def file_digest(root, relative):
    target = Path(root) / relative
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _collapse(text):
    """Collapse runs of whitespace to a single space.

    Markdown wraps a sentence across lines; the citation "Register 20 §5"
    lives on two lines in the frozen baseline. Collapsing whitespace is a
    deterministic, lossless normalisation of that line wrapping — it is not
    fuzzy matching. No character is dropped, no synonym is accepted and no
    case is folded.
    """
    return " ".join(str(text).split())


def carries(root, relative, wording):
    """True when ``relative`` exists and really contains ``wording``.

    Compared after whitespace collapsing on both sides, so a citation that
    the document wraps across lines still matches exactly.
    """
    target = Path(root) / relative
    if not target.is_file() or not str(wording).strip():
        return False
    haystack = _collapse(target.read_text(encoding="utf-8", errors="replace"))
    return _collapse(wording) in haystack


def validate_erratum(root, erratum):
    """Return a machine readable code, or ``""`` when the erratum is sound."""
    if not isinstance(erratum, dict):
        return "erratum_not_an_object"
    unknown = sorted(set(erratum) - set(ERRATUM_FIELDS))
    if unknown:
        return "erratum_unknown_field"
    missing = sorted(set(ERRATUM_FIELDS) - set(erratum))
    if missing:
        return "erratum_missing_field"
    if not str(erratum["erratum_id"]).strip():
        return "erratum_id_missing"
    if not str(erratum["invalid_reference"]).strip():
        return "erratum_reference_missing"
    if not str(erratum["reason"]).strip():
        return "erratum_reason_missing"
    if not _UTC_RE.match(str(erratum["recorded_at_utc"])):
        return "erratum_timestamp_invalid"
    if not _COMMIT_RE.match(str(erratum["source_commit"])):
        return "erratum_source_commit_invalid"

    declared = str(erratum["affected_document_sha256"])
    if not _SHA_RE.match(declared):
        return "erratum_document_digest_invalid"
    actual = file_digest(root, erratum["affected_document"])
    if actual is None:
        return "erratum_document_missing"
    if actual != declared:
        # The frozen document changed. An erratum may never float.
        return "erratum_document_digest_mismatch"

    if not carries(root, erratum["affected_document"], erratum["invalid_reference"]):
        # The erratum must correct something the document really says.
        return "erratum_reference_not_in_document"
    if not carries(root, erratum["affected_document"], erratum["citing_section"]):
        return "erratum_citing_section_not_in_document"

    anchors = erratum["replacement_anchors"]
    if not isinstance(anchors, list) or not anchors:
        return "erratum_without_replacement_anchor"
    for anchor in anchors:
        if not isinstance(anchor, dict) or sorted(anchor) != sorted(ANCHOR_FIELDS):
            return "erratum_anchor_malformed"
        if anchor["path"] == erratum["affected_document"]:
            # Circular: the frozen document cannot repair its own citation.
            return "erratum_anchor_is_the_affected_document"
        if not carries(root, anchor["path"], anchor["quote_anchor"]):
            return "erratum_anchor_does_not_carry"
    return ""


def resolve(root, reference, *, errata=None):
    """Resolve one reference through exactly one valid erratum.

    A reference whose target really exists never reaches this function; the
    caller establishes direct resolution first. This layer exists precisely
    for the case where the wording is present in a frozen document and still
    points nowhere.
    """
    errata = load_errata(root) if errata is None else errata

    matching = [
        erratum
        for erratum in errata
        if str(erratum.get("invalid_reference", "")) == str(reference)
    ]
    if len(matching) > 1:
        return Resolution(False, "ambiguous_erratum")
    if not matching:
        return Resolution(False, "unresolved_reference")

    erratum = matching[0]
    code = validate_erratum(root, erratum)
    if code:
        return Resolution(False, code, erratum_id=erratum.get("erratum_id", ""))

    # No chaining: a replacement anchor may not itself be an invalid
    # reference that only another erratum repairs.
    invalid_references = {
        str(item.get("invalid_reference", "")) for item in errata
    }
    for anchor in erratum["replacement_anchors"]:
        if anchor["quote_anchor"] in invalid_references:
            return Resolution(
                False, "chained_erratum", erratum_id=erratum["erratum_id"]
            )

    return Resolution(
        True,
        "resolved_via_erratum",
        via="erratum",
        erratum_id=erratum["erratum_id"],
        anchors=erratum["replacement_anchors"],
    )


def unresolved_references(root, references, errata=None):
    """Return ``(reference, code)`` for every reference that fails."""
    errata = load_errata(root) if errata is None else errata
    failures = []
    for reference in references:
        outcome = resolve(root, reference, errata=errata)
        if not outcome.resolved:
            failures.append((reference, outcome.code))
    return sorted(failures)

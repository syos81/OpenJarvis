"""Governance checks for B0a-2: collisions, IDs, placeholder, order.

Everything here is mechanical. Titles are read from the primary sources at the
declared commits, collisions are detected by comparing the complete ID stock of
both lines, and the canonical order is validated field by field. Free text
never establishes a fact.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import gitutil

AMBIENT_PLACEHOLDER = "{{DEC_ID_AMBIENT_INTERACTION_V1}}"
REGISTER_PATH = "docs/personal-jarvis/decisions-register.md"
ADR_DIR = "docs/adr"

DEC_TOKEN_RE = re.compile(r"\bDEC-\d{3}\b")
ADR_TOKEN_RE = re.compile(r"\bADR-\d{4}\b")
DEC_ROW_RE = re.compile(r"^\|\s*(DEC-\d{3})\s*\|")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

GOVERNANCE_DOC_DIR = Path("docs") / "governance"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git_file(commit, path, cwd):
    code, out, _ = gitutil.run_git(["show", f"{commit}:{path}"], cwd=cwd)
    return out if code == 0 else None


# --------------------------------------------------------------------------
# Primary source readers
# --------------------------------------------------------------------------
def register_titles(commit, cwd):
    """Return ``{DEC-xxx: title}`` from the decision register at ``commit``."""
    content = git_file(commit, REGISTER_PATH, cwd)
    if content is None:
        return None
    titles = {}
    for line in content.splitlines():
        match = DEC_ROW_RE.match(line)
        if not match:
            continue
        cell = line.split("|")[2].strip()
        bold = re.match(r"\*\*(.+?)\*\*", cell)
        titles[match.group(1)] = (bold.group(1) if bold else cell).rstrip(":;,. ")
    return titles


def adr_entries(commit, cwd):
    """Return ``{ADR-xxxx: (filename, h1)}`` for the ADR directory at ``commit``."""
    code, out, _ = gitutil.run_git(
        ["ls-tree", "--name-only", f"{commit}", f"{ADR_DIR}/"], cwd=cwd
    )
    if code != 0:
        return None
    entries = {}
    for path in sorted(out.split()):
        name = Path(path).name
        match = re.match(r"^(ADR-\d{4})-", name)
        if not match:
            continue
        content = git_file(commit, path, cwd) or ""
        h1 = ""
        for line in content.splitlines():
            if line.startswith("# "):
                h1 = line[2:].strip()
                break
        entries[match.group(1)] = (name, h1)
    return entries


def cited_adr_title(h1, adr_id):
    return h1.split(": ", 1)[1] if h1.startswith(f"{adr_id}:") else h1


# --------------------------------------------------------------------------
# Collision detection
# --------------------------------------------------------------------------
def detect_collisions(registry, cwd):
    """Detect every ID that both lines occupy differently.

    Returns ``(detected_ids, error)``.
    """
    lines = registry["lines"]
    canonical = lines["canonical"]["commit"]
    contacts = lines["contacts_calendar"]["commit"]

    canonical_dec = register_titles(canonical, cwd)
    contacts_dec = register_titles(contacts, cwd)
    if canonical_dec is None or contacts_dec is None:
        return set(), "decision_register_unreadable"

    detected = set()
    for identifier in sorted(set(canonical_dec) & set(contacts_dec)):
        if canonical_dec[identifier] != contacts_dec[identifier]:
            detected.add(identifier)

    canonical_adr = adr_entries(canonical, cwd)
    contacts_adr = adr_entries(contacts, cwd)
    if canonical_adr is None or contacts_adr is None:
        return detected, "adr_directory_unreadable"
    for identifier in sorted(set(canonical_adr) & set(contacts_adr)):
        if canonical_adr[identifier] != contacts_adr[identifier]:
            detected.add(identifier)
    return detected, None


def verify_collision_sides(registry, cwd):
    """Verify every declared side against its primary source. Yields issues."""
    lines = registry["lines"]
    caches = {}
    for collision in registry["collisions"]:
        identifier = collision["id"]
        seen_lines = set()
        for side in collision["sides"]:
            line_key = side["line"]
            if line_key not in lines:
                yield (identifier, "collision_line_unknown")
                continue
            if line_key in seen_lines:
                yield (identifier, "collision_line_duplicated")
            seen_lines.add(line_key)
            commit = lines[line_key]["commit"]
            if collision["kind"] == "DEC":
                key = ("dec", commit)
                if key not in caches:
                    caches[key] = register_titles(commit, cwd)
                titles = caches[key]
                if titles is None:
                    yield (identifier, "collision_primary_source_unreadable")
                    continue
                actual = titles.get(identifier)
                if actual is None:
                    yield (identifier, "collision_side_missing")
                elif actual != side["title"]:
                    yield (identifier, "collision_title_mismatch")
                if side["primary_source"] != REGISTER_PATH:
                    yield (identifier, "collision_primary_source_mismatch")
            else:
                key = ("adr", commit)
                if key not in caches:
                    caches[key] = adr_entries(commit, cwd)
                entries = caches[key]
                if entries is None:
                    yield (identifier, "collision_primary_source_unreadable")
                    continue
                entry = entries.get(identifier)
                if entry is None:
                    yield (identifier, "collision_side_missing")
                    continue
                filename, h1 = entry
                if cited_adr_title(h1, identifier) != side["title"]:
                    yield (identifier, "collision_title_mismatch")
                if side["primary_source"] != f"{ADR_DIR}/{filename}":
                    yield (identifier, "collision_primary_source_mismatch")
        if len(seen_lines) < 2:
            yield (identifier, "collision_side_missing")


# --------------------------------------------------------------------------
# Qualified citations
# --------------------------------------------------------------------------
def strip_code(text):
    """Remove fenced blocks and inline code spans before scanning prose."""
    without_fences = FENCE_RE.sub(" ", text)
    return INLINE_CODE_RE.sub(" ", without_fences)


def citation_index(citations):
    index = {}
    for entry in citations["citations"]:
        index.setdefault(entry["id"], []).append(entry)
    return index


def check_document_citations(text, index):
    """Yield ``(identifier, reason_code)`` for every unqualified reference."""
    prose = strip_code(text)
    for match in list(DEC_TOKEN_RE.finditer(prose)) + list(
        ADR_TOKEN_RE.finditer(prose)
    ):
        identifier = match.group(0)
        entries = index.get(identifier)
        if not entries:
            yield (identifier, "reference_id_unknown")
            continue
        tail = prose[match.end() : match.end() + 400]
        qualified = any(
            tail.startswith(f" ({entry['line_label']}, „{entry['title']}\")")
            for entry in entries
        )
        if not qualified:
            yield (identifier, "reference_not_qualified")


# --------------------------------------------------------------------------
# Canonical delivery order
# --------------------------------------------------------------------------
EXPECTED_ORDER = (
    (1, "Kontakte", "fachmodul", 1, True),
    (2, "Kalender", "fachmodul", 2, True),
    (3, "Ambient Interaction V1", "technischer_produktblock", None, False),
    (4, "Trading Intelligence T1", "fachmodul", 3, True),
)

ORDER_FIELDS = (
    "delivery_position",
    "element_type",
    "canonical_name",
    "fachmodul_number",
    "owns_domain_data",
    "normative_sources",
    "acceptance_profile",
)


def check_delivery_order(order):
    """Yield ``(subject, reason_code)`` for every violated order rule."""
    elements = order.get("elements") or []
    positions = []
    for element in elements:
        missing = [field for field in ORDER_FIELDS if field not in element]
        if missing:
            yield (element.get("canonical_name", "?"), "order_field_missing")
            continue
        position = element["delivery_position"]
        if not isinstance(position, int):
            yield (element["canonical_name"], "delivery_position_missing")
            continue
        positions.append(position)

    if len(positions) != len(set(positions)):
        yield ("order", "delivery_position_duplicated")
    fixed = sorted(position for position in positions if position <= 4)
    if fixed != [1, 2, 3, 4]:
        yield ("order", "delivery_position_gap")

    by_position = {
        element["delivery_position"]: element
        for element in elements
        if isinstance(element.get("delivery_position"), int)
    }
    for position, name, kind, number, ownership in EXPECTED_ORDER:
        element = by_position.get(position)
        if element is None:
            yield (name, "element_missing_at_position")
            continue
        if element["canonical_name"] != name:
            yield (name, "element_not_at_expected_position")
            continue
        if element["element_type"] != kind:
            yield (name, "element_type_mismatch")
        if element["fachmodul_number"] != number:
            yield (
                name,
                "fachmodul_number_present"
                if number is None
                else "fachmodul_number_mismatch",
            )
        if bool(element["owns_domain_data"]["value"]) != ownership:
            yield (
                name,
                "domain_data_ownership_present"
                if ownership is False
                else "domain_data_ownership_missing",
            )
        if number is not None and element["fachmodul_number"] == position and (
            number != position
        ):
            yield (name, "position_and_module_number_confused")

    for element in elements:
        number = element.get("fachmodul_number")
        position = element.get("delivery_position")
        if (
            isinstance(number, int)
            and isinstance(position, int)
            and position > 3
            and number == position
        ):
            yield (element.get("canonical_name", "?"), "position_and_module_number_confused")
        if isinstance(position, int) and position > 4:
            if not element.get("owner_decision"):
                yield (
                    element.get("canonical_name", "?"),
                    "additional_element_without_owner_decision",
                )

    if order.get("ambient_placeholder") != AMBIENT_PLACEHOLDER:
        yield ("ambient", "ambient_placeholder_replaced")

    forbidden = {entry["id"] for entry in order.get("forbidden_order_sources", [])}
    if forbidden != {"DEC-049", "ADR-0024"}:
        yield ("order", "forbidden_order_source_declaration_wrong")
    for element in elements:
        for source in element.get("normative_sources", []):
            if source.get("id") in forbidden:
                yield (element["canonical_name"], "wrong_order_source_assigned")

    ambient = by_position.get(3)
    if ambient is not None:
        ids = {source.get("id") for source in ambient.get("normative_sources", [])}
        if AMBIENT_PLACEHOLDER not in ids:
            yield ("ambient", "ambient_source_not_the_placeholder")


MARKDOWN_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*([^|]+?)\s*\|$"
)
TYPE_LABELS = {
    "Fachmodul": "fachmodul",
    "technischer Produktblock": "technischer_produktblock",
}


def parse_order_document(text):
    """Parse the human readable order table into comparable records."""
    rows = []
    for line in text.splitlines():
        match = MARKDOWN_ROW_RE.match(line.strip())
        if not match:
            continue
        position, name, kind, number, ownership = match.groups()
        rows.append(
            {
                "delivery_position": int(position),
                "canonical_name": name.strip(),
                "element_type": TYPE_LABELS.get(kind.strip(), kind.strip()),
                "fachmodul_number": (
                    int(number) if number.strip().isdigit() else None
                ),
                "owns_domain_data": ownership.strip().lower().startswith("ja"),
            }
        )
    return rows


def check_document_consistency(order, document_text):
    """Yield ``(subject, reason_code)`` when document and source disagree."""
    rows = {row["delivery_position"]: row for row in parse_order_document(document_text)}
    if not rows:
        yield ("order_document", "order_document_table_missing")
        return
    for element in order.get("elements", []):
        position = element.get("delivery_position")
        row = rows.get(position)
        if row is None:
            yield (element.get("canonical_name", "?"), "order_document_row_missing")
            continue
        if row["canonical_name"] != element["canonical_name"]:
            yield (element["canonical_name"], "order_document_name_mismatch")
        if row["element_type"] != element["element_type"]:
            yield (element["canonical_name"], "order_document_type_mismatch")
        if row["fachmodul_number"] != element["fachmodul_number"]:
            yield (element["canonical_name"], "order_document_module_number_mismatch")
        if row["owns_domain_data"] != bool(element["owns_domain_data"]["value"]):
            yield (element["canonical_name"], "order_document_ownership_mismatch")
    for position in rows:
        if position not in {
            element.get("delivery_position") for element in order.get("elements", [])
        }:
            yield (str(position), "order_document_extra_row")

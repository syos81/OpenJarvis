"""Mechanical generality checks (B0a-2 §10).

Three independent mechanisms:

1. **Organisation name scan** — token exact and unicode normalised, never a
   naive global substring test, with precise path rules.
2. **Provider path gate** — provider terms only inside explicitly released
   adapter, manifest and capability paths; no blanket allowlist.
3. **Hard coded literal comparisons** — an AST check that forbids comparing
   core values against organisation, workspace, process type or provider
   literals.

The positive configuration test with two invented organisations lives in the
test harness; this module supplies its file classification and activation
condition.
"""

from __future__ import annotations

import ast
import fnmatch
import re
import unicodedata
from pathlib import Path

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".icns", ".zip", ".gz",
    ".woff", ".woff2", ".ttf", ".otf", ".so", ".dylib", ".lock", ".xcuserstate",
}


def normalize(text):
    """Fold case and strip diacritics so ``Klünder`` matches ``Kluender``."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


#: Identifier chunks: everything between non alphanumeric characters.
_CHUNK_RE = re.compile(r"[^0-9A-Za-zÀ-ɏ]+")
#: Sub-tokens inside a chunk, including camel case humps.
_SEGMENT_RE = re.compile(
    r"[A-ZÀ-Þ]+(?![a-zß-ÿ])"
    r"|[A-ZÀ-Þ]?[a-zß-ɏ]+"
    r"|[0-9]+"
)


def segments(text):
    """Split ``text`` into normalised identifier segments.

    ``kluender_contacts`` and ``KluenderContacts`` both yield ``kluender``;
    ``standard`` and ``dartboard`` stay single segments and therefore never
    match ``dart``. This is what makes the scan token exact instead of a naive
    substring test.
    """
    result = []
    for chunk in _CHUNK_RE.split(text):
        if not chunk:
            continue
        for segment in _SEGMENT_RE.findall(chunk):
            result.append(normalize(segment))
    return result


def term_variants(variants):
    """Normalised spellings of one term, ready for segment comparison."""
    return {normalize(variant) for variant in variants if variant}


def count_term(text, normalised_variants):
    if not normalised_variants:
        return 0
    return sum(1 for segment in segments(text) if segment in normalised_variants)


def matches_any(path, patterns):
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def in_scope(path, scope):
    if not matches_any(path, scope["include"]):
        return False
    return not matches_any(path, scope["exclude"])


def candidate_files(root, tracked_paths, scope):
    """Deterministically ordered files that the scan classifies as in scope."""
    selected = []
    for path in sorted(tracked_paths):
        if not in_scope(path, scope):
            continue
        target = Path(root) / path
        if not target.is_file() or target.suffix.lower() in BINARY_SUFFIXES:
            continue
        selected.append(path)
    return selected


def declared_identifier_masks(path, declared):
    """Normalised literals that are declared for exactly this path.

    A declared identifier is not a blanket exemption: it is pinned by exact
    value and by an exact path list. Any other occurrence of the term — in a
    schema, enum, route, type or module name, or in a different file — is
    still reported.
    """
    masks = []
    for entry in declared or []:
        if path in (entry.get("paths") or []):
            masks.append(entry["value"])
    return masks


def check_declared_identifiers(root, declared):
    """Yield ``(value_id, path, reason_code)`` for stale declarations."""
    for entry in declared or []:
        for path in entry.get("paths") or []:
            target = Path(root) / path
            if not target.is_file():
                yield (entry["identifier_id"], path, "declared_identifier_path_absent")
                continue
            content = target.read_text(encoding="utf-8", errors="ignore")
            if entry["value"].casefold() not in content.casefold():
                yield (entry["identifier_id"], path, "declared_identifier_stale")


def scan_terms(root, files, terms, declared=None):
    """Return sorted findings ``{path, term_id, count, location}``.

    Both the file content and the path itself are examined, so an
    organisation in a module, file or directory name is caught as well.
    """
    active = []
    for term in terms:
        if term.get("status") != "active":
            continue
        variants = term_variants(term.get("variants") or [])
        if variants:
            active.append((term["term_id"], variants))

    findings = []
    for path in files:
        try:
            content = (Path(root) / path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for mask in declared_identifier_masks(path, declared):
            content = re.sub(re.escape(mask), " ", content, flags=re.IGNORECASE)
        for term_id, variants in active:
            in_path = count_term(path, variants)
            in_content = count_term(content, variants)
            if in_path:
                findings.append(
                    {
                        "path": path,
                        "term_id": term_id,
                        "count": in_path,
                        "location": "path",
                    }
                )
            if in_content:
                findings.append(
                    {
                        "path": path,
                        "term_id": term_id,
                        "count": in_content,
                        "location": "content",
                    }
                )
    return sorted(
        findings, key=lambda item: (item["path"], item["term_id"], item["location"])
    )


def pending_terms(terms):
    return sorted(
        term["term_id"] for term in terms if term.get("status") == "pending_owner_input"
    )


def provider_violations(findings, allowed_paths):
    """Provider findings outside the explicitly released paths."""
    return [
        finding
        for finding in findings
        if not matches_any(finding["path"], allowed_paths)
    ]


# --------------------------------------------------------------------------
# Hard coded literal comparisons
# --------------------------------------------------------------------------
def _identifier_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "get" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
    return None


def _is_sensitive(identifier, sensitive):
    if not identifier:
        return False
    lowered = identifier.lower()
    return any(marker in lowered for marker in sensitive)


def _literal_operands(node):
    literals = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        literals.append(node.value)
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                literals.append(element.value)
    return literals


def find_literal_comparisons(source, sensitive, filename="<core>",
                             provider_values=None):
    """Yield ``(identifier, literal, line)`` for forbidden literal compares.

    Organisation, workspace, process type and domain state identifiers may not
    be compared against *any* literal — they are configuration. Provider
    identifiers may only not be compared against an actual provider value; a
    comparison against an error class such as ``"timeout"`` is not a provider
    decision and stays allowed outside the adapter boundary.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError:
        return []
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left] + list(node.comparators)
        identifiers = [_identifier_of(operand) for operand in operands]
        sensitive_hit = next(
            (
                identifier
                for identifier in identifiers
                if _is_sensitive(identifier, sensitive)
            ),
            None,
        )
        if not sensitive_hit:
            continue
        provider_only = "provider" in sensitive_hit.lower()
        known_providers = {value.casefold() for value in (provider_values or [])}
        for operand in operands:
            for literal in _literal_operands(operand):
                if provider_only and literal.casefold() not in known_providers:
                    continue
                findings.append(
                    {
                        "identifier": sensitive_hit,
                        "literal_length": len(literal),
                        "line": getattr(node, "lineno", 0),
                    }
                )
    return sorted(findings, key=lambda item: (item["identifier"], item["line"]))


# --------------------------------------------------------------------------
# Activation of the positive configuration test
# --------------------------------------------------------------------------
class ActivationError(ValueError):
    """Raised when the activation declaration is structurally unusable."""

    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def process_paths_present(root, activation):
    """Return the sorted product paths that activate the positive test.

    Rule R10: a missing glob key must not read as an empty pattern list —
    that would silently report ``inactive`` and waive the mandatory positive
    product test. A present-but-empty list stays a legitimate declaration.
    """
    missing = [
        key
        for key in ("schema_globs", "route_globs", "core_globs")
        if key not in activation
    ]
    if missing:
        raise ActivationError("process_activation_key_missing", ",".join(missing))
    found = []
    for key in ("schema_globs", "route_globs", "core_globs"):
        for pattern in activation.get(key, []):
            for match in sorted(Path(root).glob(pattern)):
                if match.is_file():
                    found.append(str(match.relative_to(root)))
    return sorted(set(found))


def activation_state(root, activation):
    """``('active', paths)`` once a process product path exists."""
    paths = process_paths_present(root, activation)
    return ("active" if paths else "inactive"), paths

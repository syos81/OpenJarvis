"""PII normalisation, leak detection and canary matching.

Two jobs live here:

1. ``normalize_text`` / ``scrub`` remove the volatile and personal parts of
   tool output *before* a cause signature or a short message is derived from
   it. Raw output itself is never routed through the sanitized path.
2. ``find_violations`` / ``assert_clean`` are the guard rails for everything
   that may leave the gitignored runtime area: machine JSON on stdout,
   progress output on stderr, sanitized evidence, cache metadata and cause
   signatures.

``contains_canary`` additionally matches encoded and unicode-normalised
variants, so a leak cannot hide behind base64, percent encoding or NFD.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
import urllib.parse

# --------------------------------------------------------------------------
# Masks applied first: they are structurally safe and would otherwise trip the
# phone-number heuristic below.
# --------------------------------------------------------------------------
_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DIGEST_RE = re.compile(r"\b[0-9a-f]{32,128}\b", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ADDR_RE = re.compile(r"\b0x[0-9a-fA-F]{4,}\b")
_PID_RE = re.compile(r"\b(pid|PID|process)[ =:]+\d+\b")
_TMPDIR_RE = re.compile(r"/(?:private/)?(?:var/folders|tmp)/[^\s'\"]*")
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/[^/\s'\":]+(?:/[^\s'\":]*)?")
_TILDE_RE = re.compile(r"(?<![\w])~/[^\s'\"]*")
_EMAIL_RE = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<![\w.])\+?\d[\d ()/.-]{6,}\d(?![\w.])")
_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}"
    r"|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
_SECRET_KV_RE = re.compile(
    r"\b(?:token|secret|password|passwd|api[_-]?key|authorization|cookie)"
    r"\s*[=:]\s*\S+",
    re.IGNORECASE,
)
_RANDOM_TMPNAME_RE = re.compile(r"\b(?:tmp|temp)[A-Za-z0-9_]{6,}\b")

#: Order matters — earlier entries mask text the later ones would misread.
_NORMALISERS = (
    ("<ts>", _TIMESTAMP_RE),
    ("<date>", _DATE_RE),
    ("<uuid>", _UUID_RE),
    ("<addr>", _ADDR_RE),
    ("<pid>", _PID_RE),
    ("<tmp>", _TMPDIR_RE),
    ("<home>", _HOME_PATH_RE),
    ("<home>", _TILDE_RE),
    ("<tmpname>", _RANDOM_TMPNAME_RE),
    ("<digest>", _DIGEST_RE),
    ("<secret>", _TOKEN_RE),
    ("<secret>", _SECRET_KV_RE),
    ("<email>", _EMAIL_RE),
    ("<phone>", _PHONE_RE),
)

#: Patterns that must never appear in sanitized output, with their reason code.
#: They are checked after the structurally harmless masks have been applied.
_VIOLATION_PATTERNS = (
    ("pii_email", _EMAIL_RE),
    ("pii_secret", _TOKEN_RE),
    ("pii_secret_assignment", _SECRET_KV_RE),
    ("pii_absolute_user_path", _HOME_PATH_RE),
    ("pii_home_shorthand", _TILDE_RE),
    ("pii_uuid", _UUID_RE),
    ("pii_phone", _PHONE_RE),
)

_PRE_VIOLATION_MASKS = (
    ("<ts>", _TIMESTAMP_RE),
    ("<date>", _DATE_RE),
    ("<digest>", _DIGEST_RE),
)


class EvidenceLeakError(Exception):
    """Raised when sanitized output would carry personal or secret data."""

    def __init__(self, violations):
        self.violations = list(violations)
        codes = ", ".join(sorted({v["code"] for v in self.violations}))
        super().__init__(f"sanitized output rejected ({codes})")


def normalize_text(text: str) -> str:
    """Replace volatile and personal fragments with stable placeholders."""
    if not text:
        return ""
    normalised = unicodedata.normalize("NFKC", text)
    normalised = normalised.replace("​", "").replace("﻿", "")
    for placeholder, pattern in _NORMALISERS:
        normalised = pattern.sub(placeholder, normalised)
    return normalised


def scrub(text: str, *, max_length: int = 240) -> str:
    """Normalise ``text`` and clamp it to a short, single-line message."""
    normalised = normalize_text(text)
    normalised = " ".join(normalised.split())
    if len(normalised) > max_length:
        normalised = normalised[: max_length - 1] + "…"
    return normalised


def find_violations(value, path: str = "$"):
    """Walk ``value`` and report every PII/secret pattern that survives."""
    violations = []
    _walk(value, path, violations)
    return violations


def _walk(value, path, violations):
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            _walk(key, f"{path}.<key>", violations)
            _walk(value[key], f"{path}.{key}", violations)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, f"{path}[{index}]", violations)
    elif isinstance(value, str):
        masked = value
        for placeholder, pattern in _PRE_VIOLATION_MASKS:
            masked = pattern.sub(placeholder, masked)
        for code, pattern in _VIOLATION_PATTERNS:
            if pattern.search(masked):
                violations.append({"code": code, "path": path})


def assert_clean(value, path: str = "$") -> None:
    violations = find_violations(value, path)
    if violations:
        raise EvidenceLeakError(violations)


# --------------------------------------------------------------------------
# Canary matching
# --------------------------------------------------------------------------
_SEPARATORS_RE = re.compile(r"[\s\-_.()/\\]+")


def _decode_candidates(text: str):
    """Yield plausible decodings of ``text`` for encoded-leak detection."""
    yield text
    try:
        yield urllib.parse.unquote(text)
    except (ValueError, UnicodeDecodeError):
        pass
    try:
        yield text.encode("ascii", "ignore").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeEncodeError, ValueError):
        pass
    for token in re.findall(r"[A-Za-z0-9+/=_-]{8,}", text):
        padded = token.replace("-", "+").replace("_", "/")
        padded += "=" * (-len(padded) % 4)
        try:
            decoded = base64.b64decode(padded, validate=False)
        except (binascii.Error, ValueError):
            continue
        try:
            yield decoded.decode("utf-8")
        except UnicodeDecodeError:
            continue


def _canonical_forms(text: str):
    forms = set()
    for candidate in _decode_candidates(text):
        for normal_form in ("NFKC", "NFD"):
            normalised = unicodedata.normalize(normal_form, candidate)
            stripped = "".join(
                ch for ch in normalised if not unicodedata.combining(ch)
            )
            for variant in (normalised, stripped):
                folded = variant.casefold()
                forms.add(folded)
                forms.add(_SEPARATORS_RE.sub("", folded))
    return forms


def contains_canary(haystack: str, needle: str) -> bool:
    """True if ``needle`` appears in ``haystack``, including encoded forms."""
    if not haystack or not needle:
        return False
    haystack_forms = _canonical_forms(haystack)
    needle_forms = {form for form in _canonical_forms(needle) if len(form) >= 4}
    return any(
        needle_form in haystack_form
        for needle_form in needle_forms
        for haystack_form in haystack_forms
    )


def find_canaries(value, canaries):
    """Return sorted ``(canary_id, path)`` hits inside a nested structure."""
    hits = []

    def _visit(node, path):
        if isinstance(node, dict):
            for key in sorted(node, key=str):
                _visit(str(key), f"{path}.<key>")
                _visit(node[key], f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                _visit(item, f"{path}[{index}]")
        elif isinstance(node, str):
            for canary_id, canary_value in sorted(canaries.items()):
                if contains_canary(node, canary_value):
                    hits.append((canary_id, path))

    _visit(value, "$")
    return sorted(set(hits))

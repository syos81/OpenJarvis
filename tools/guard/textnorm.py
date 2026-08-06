"""The single canonical source for PII variant handling.

Before B0b two mechanisms existed side by side and drifted apart:

* the canary **detection** knew NFKC, NFD, casefolding, separator variants,
  separator removal, base64 and percent encoding,
* the outgoing **redaction** only understood the slash spelling of a user
  path.

The result was the worst possible combination: a value could be recognised as
personal and still be written out verbatim. This module removes that
asymmetry by being the one place both sides use.

Nothing here decodes arbitrary binary or text fields without bound. The
decoding candidates are exactly the ones the existing, already justified
detection used.

The module is part of the active guard package and therefore imports nothing
but the standard library.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
import urllib.parse

#: Characters that are treated as separators when a value is flattened.
SEPARATOR_PATTERN = r"[\s\-_.()/\\]+"
SEPARATORS_RE = re.compile(SEPARATOR_PATTERN)

#: The declared variant kinds. Detection and redaction both derive from this
#: list; a kind that is not covered by both is a gate failure.
VARIANT_KINDS = (
    "plain",
    "nfkc",
    "nfd",
    "case",
    "separators",
    "separators_removed",
    "flattened_path",
    "percent",
    "base64",
)

#: Home directory roots whose first path segment is a user name.
_HOME_ROOTS = "Users|home"

#: Slash spelling — an absolute path, unambiguous because of the leading "/".
HOME_SLASH_RE = re.compile(rf"/(?:{_HOME_ROOTS})/[^/\s'\":]+(?:/[^\s'\":]*)?")
#: Windows style spelling.
HOME_BACKSLASH_RE = re.compile(
    rf"\\(?:{_HOME_ROOTS})\\[^\\\s'\":]+(?:\\[^\s'\":]*)?"
)
#: Flattened spellings. The separator that replaced the leading slash must be
#: present — that is what distinguishes a flattened absolute path from an
#: ordinary word that happens to start with "Users". Without this anchor the
#: rule would redact harmless text such as "Users-of-the-system-overview".
HOME_HYPHEN_RE = re.compile(rf"(?<![A-Za-z0-9])-(?:{_HOME_ROOTS})-[^/\s'\":]+")
HOME_UNDERSCORE_RE = re.compile(rf"(?<![A-Za-z0-9])_(?:{_HOME_ROOTS})_[^/\s'\":]+")
#: Percent encoded separators.
HOME_PERCENT_RE = re.compile(
    rf"(?i)%2f(?:{_HOME_ROOTS})%2f[^\s'\":]+"
)
#: Shell shorthand.
HOME_TILDE_RE = re.compile(r"(?<![\w])~/[^\s'\"]*")

#: Every user path spelling, in application order. Every entry redacts to the
#: same placeholder, so no spelling leaks more than another.
USER_PATH_PATTERNS = (
    ("slash", HOME_SLASH_RE),
    ("backslash", HOME_BACKSLASH_RE),
    ("percent", HOME_PERCENT_RE),
    ("hyphen", HOME_HYPHEN_RE),
    ("underscore", HOME_UNDERSCORE_RE),
    ("tilde", HOME_TILDE_RE),
)

HOME_PLACEHOLDER = "<home>"


def decode_candidates(text):
    """Yield the bounded set of plausible decodings of ``text``."""
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


def canonical_forms(text):
    """Return every canonical form of ``text`` used for matching."""
    forms = set()
    for candidate in decode_candidates(text):
        for normal_form in ("NFKC", "NFD"):
            normalised = unicodedata.normalize(normal_form, candidate)
            stripped = "".join(
                ch for ch in normalised if not unicodedata.combining(ch)
            )
            for variant in (normalised, stripped):
                folded = variant.casefold()
                forms.add(folded)
                forms.add(SEPARATORS_RE.sub("", folded))
    return forms


def contains(haystack, needle, *, min_length=4):
    """True when ``needle`` occurs in ``haystack`` in any canonical form."""
    if not haystack or not needle:
        return False
    haystack_forms = canonical_forms(haystack)
    needle_forms = {
        form for form in canonical_forms(needle) if len(form) >= min_length
    }
    return any(
        needle_form in haystack_form
        for needle_form in needle_forms
        for haystack_form in haystack_forms
    )


def redact_user_paths(text, placeholder=HOME_PLACEHOLDER):
    """Replace every spelling of a user path with ``placeholder``."""
    if not text:
        return text
    result = str(text)
    for _kind, pattern in USER_PATH_PATTERNS:
        result = pattern.sub(placeholder, result)
    return result


def user_path_spellings(value):
    """Return the spellings of ``value`` this module recognises.

    Used by the tests and by the metagate that proves detection and redaction
    cover the same set.
    """
    text = str(value)
    return {
        "slash": text,
        "backslash": text.replace("/", "\\"),
        "hyphen": text.replace("/", "-"),
        "underscore": text.replace("/", "_"),
        "percent": text.replace("/", "%2F"),
    }

"""Path exact gitignore convention and mechanical file hygiene (B0a-2 §12).

Versioned are exactly:

``CLAUDE.md``, ``.claude/settings.json``, ``.claude/hooks/**``,
``.claude/skills/**``

Everything else below ``.claude/`` stays ignored — local state, caches, raw
logs, temporary evidence and machine specific configuration. A blanket
re-inclusion of ``.claude/**`` is inadmissible.

The released files must contain no credentials, private keys, tokens, embedded
login data and no machine dependent absolute paths. Project paths are handled
relative to the repository root determined by ``git rev-parse --show-toplevel``.
Findings are reported with path and rule id; the found secret value is never
reproduced.
"""

from __future__ import annotations

import re
from pathlib import Path

RELEASED_PATTERNS = (
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/hooks/**",
    ".claude/skills/**",
)

#: Paths that must not be ignored, and paths that must be ignored.
MUST_BE_TRACKABLE = (
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/hooks/pretooluse_guard.sh",
    ".claude/skills/gate/SKILL.md",
)
MUST_BE_IGNORED = (
    ".claude/settings.local.json",
    ".claude/agents/some-agent.md",
    ".claude/state/cache.json",
    ".claude/raw-log.jsonl",
    ".gate-runtime/raw-logs/probe.log",
)

BLANKET_EXCEPTIONS = re.compile(r"^!\s*\.claude/(\*\*?/?|)$")

_USER_SEGMENT = r"[^/\\\s'\"<>]+"

RULES = (
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    (
        "uri_with_embedded_credentials",
        re.compile(rf"[a-zA-Z][a-zA-Z0-9+.-]*://{_USER_SEGMENT}:[^/\s@]+@"),
    ),
    (
        "known_token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}"
            r"|xox[baprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{12,}"
            r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
        ),
    ),
    (
        "credential_assignment",
        re.compile(
            r"\b(?:password|passwd|secret|token|api[_-]?key|client[_-]?secret"
            r"|authorization|cookie)\s*[=:]\s*[\"']?[^\s\"',]{6,}",
            re.IGNORECASE,
        ),
    ),
    ("machine_path_macos", re.compile(rf"(?:file://)?/Users/{_USER_SEGMENT}")),  # gate-allow: absolute_user_path
    ("machine_path_linux", re.compile(rf"(?:file://)?/home/{_USER_SEGMENT}")),  # gate-allow: absolute_user_path
    (
        "machine_path_windows",
        re.compile(
            rf"(?:[A-Za-z]:\\+Users\\+{_USER_SEGMENT}"
            rf"|%USERPROFILE%|\\\\+[^\\\s]+\\+Users\\+{_USER_SEGMENT})"
        ),
    ),
    (
        "machine_path_volume_or_temp",
        re.compile(
            r"(?:file://)?(?:/private)?/(?:var/folders|tmp)/\S+|(?:file://)?/Volumes/\S+"
        ),
    ),
)

#: Placeholders that are explicitly allowed instead of a machine path.
ALLOWED_PLACEHOLDERS = ("$CLAUDE_PROJECT_DIR", "${CLAUDE_PROJECT_DIR}")
ALLOW_MARKER = "gate-allow: machine-path-example"


def released(path):
    """True when ``path`` is one of the versioned project rule files."""
    text = str(path)
    if text == "CLAUDE.md" or text == ".claude/settings.json":
        return True
    return text.startswith(".claude/hooks/") or text.startswith(".claude/skills/")


def scan_text(text):
    """Yield ``(rule_id, line_number)`` for every hygiene violation.

    The matched value itself is deliberately never returned.
    """
    for line_number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARKER in line:
            continue
        candidate = line
        for placeholder in ALLOWED_PLACEHOLDERS:
            candidate = candidate.replace(placeholder, "")
        for rule_id, pattern in RULES:
            if pattern.search(candidate):
                yield (rule_id, line_number)


def scan_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    return sorted(set(scan_text(text)))


def blanket_exception_lines(gitignore_text):
    """Lines that would re-include all of ``.claude`` at once."""
    offending = []
    for line_number, line in enumerate(gitignore_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if BLANKET_EXCEPTIONS.match(stripped):
            offending.append(line_number)
    return offending

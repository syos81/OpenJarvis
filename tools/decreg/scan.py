"""Number state of a line, determined from allocations rather than mentions.

B0b determined the number state with a text scan over every markdown file.
That method cannot tell an allocation from a mention: the B0b handoff said in
prose that two numbers were free, and a later run of the same scan reported
exactly those two numbers as taken *because the sentence named them*. The
method was unreliable in both directions and could never carry a safe
allocation decision.

An allocation is a row in a decision register table whose first cell is the
decision id. Everything else — prose, reports, commit messages, this
docstring — is a mention and changes nothing.
"""

from __future__ import annotations

import re
import subprocess

#: A register table row: the id is the first cell of the row.
_ALLOCATION_RE = re.compile(
    r"^\|\s*\*{0,2}(DEC-(?:\d{3}|D\d{2}))\*{0,2}\s*\|", re.MULTILINE
)
#: Any occurrence at all, used by the counter test and for reporting.
_MENTION_RE = re.compile(r"\b(DEC-(?:\d{3}|D\d{2}))\b")

REGISTER_PATH = "docs/personal-jarvis/decisions-register.md"


def allocated_ids(text):
    """Decision ids allocated by ``text``, i.e. carried by a table row."""
    return set(_ALLOCATION_RE.findall(text))


def mentioned_ids(text):
    """Every decision id ``text`` names, allocated or not."""
    return set(_MENTION_RE.findall(text))


def _blob(repo, ref, path):
    completed = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "cat-file", "blob", f"{ref}:{path}"],
        cwd=str(repo),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=60,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", "replace")


def scan_line(repo, ref, register_path=REGISTER_PATH):
    """Allocations of one line at one immutable reference."""
    text = _blob(repo, ref, register_path)
    if text is None:
        return None
    return allocated_ids(text)


def scan_lines(repo, refs, register_path=REGISTER_PATH):
    """Union of the allocations of several lines.

    Returns ``(union, per_ref)``. A ref whose register cannot be read is
    reported as ``None`` rather than silently skipped.
    """
    per_ref = {}
    union = set()
    for ref in refs:
        found = scan_line(repo, ref, register_path)
        per_ref[ref] = found
        if found:
            union |= found
    return union, per_ref


def series_state(allocated, prefix, width, limit=999):
    """Return ``(used_sorted, gaps, first_unused)`` for one id series."""
    used = sorted(
        number
        for number in range(1, limit + 1)
        if f"{prefix}{number:0{width}d}" in allocated
    )
    if not used:
        return [], [], f"{prefix}{1:0{width}d}"
    gaps = [number for number in range(1, max(used) + 1) if number not in used]
    first_unused = next(
        (
            f"{prefix}{number:0{width}d}"
            for number in range(1, limit + 1)
            if number not in used
        ),
        None,
    )
    return used, gaps, first_unused

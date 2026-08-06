"""Canonical decision number reservation register.

The register is the answer to a defect B0b proved mechanically: as long as
two lines allocate decision numbers independently, freeness can only ever be
checked against frozen snapshots, never against what the other line will
allocate next. B0a-3 had to clean up exactly that collision class.

Two things live here and nowhere else:

``model``
    the append-only event model, its state machine and its hash chain.
``scan``
    the number state of a line, determined from register table rows rather
    than from free text. A mention is not an allocation — the text scan that
    B0b used could not tell the two apart and reported a number as taken
    because a report said it was free.

The register data itself never lives in a working branch. It lives on one
canonical ref; everything in this package is schema, validator and tool.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

#: The one canonical ref. A working branch never carries a copy of the data.
CANONICAL_REF = "refs/governance/dec-reservations"

#: The single append-only file on that ref.
REGISTER_FILENAME = "dec-reservations.jsonl"

__all__ = ["CANONICAL_REF", "REGISTER_FILENAME", "SCHEMA_VERSION"]

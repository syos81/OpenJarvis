"""Kanonische Digest-Bildung für Freigaben, Outbox und Audit.

Ein Digest bindet eine Freigabe an **genau die** Nutzlast, die vorbereitet
wurde. Ändert sich die Nutzlast nach der Freigabe, ändert sich der Digest und
die Freigabe passt nicht mehr (10 §3).

Der Digest ist bewusst **nicht umkehrbar**: Audit und Outbox speichern ihn
statt der Nutzlast, damit dort keine Kontaktwerte liegen (10 §5, 12 §1).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

__all__ = ["canonical_json", "digest_of"]


def canonical_json(payload: Any) -> str:
    """Deterministische Serialisierung: sortierte Schlüssel, feste Trenner."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def digest_of(payload: Any) -> str:
    """SHA-256 über die kanonische Serialisierung."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

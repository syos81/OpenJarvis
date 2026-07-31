"""Maskierung an der API-Grenze: rohe Providerkennungen verlassen sie nicht.

**Warum an der Grenze und nicht tiefer.** Persistenz, Sync und Sidecar brauchen
die echten Kennungen — ohne sie gäbe es kein Ziel für eine Enumeration und
keinen Primärschlüssel für `contacts_sync_state`. Was sie nicht brauchen, ist
ein Weg nach draußen: über HTTP genügt eine *Zuordenbarkeit* („dieselbe Zeile
wie eben"), und genau die leistet ein Kürzel.

Anlass war ein konkreter Vorfall: am 2026-07-31 stand die rohe Apple-Kennung
eines Containers (`…:ABAccount`) in einer Terminalausgabe, weil sie im
Statusvertrag stand. Die Kennung selbst ist kein Geheimnis im kryptografischen
Sinn — sie ist aber eine Apple-interne Kontoidentität, und die gehört nicht in
Logs, Screenshots oder Fehlerberichte.

**Die Bildung ist absichtlich dieselbe wie in der Auditspur**
(`sync.audit.container_ref`): so bezeichnet `C-1b3d99` in einem Bericht, in der
Datenbank und in einer API-Antwort denselben Container. Zwei Bildungen wären
zwei Wahrheiten.

Maskierung ist keine Verschlüsselung: sie ist einweg und trägt keinen
Schlüssel. Wer die rohe Kennung bereits kennt, kann ihr Kürzel nachrechnen —
das ist gewollt (Zuordnung in der Forensik) und harmlos, denn der umgekehrte
Weg bleibt zu.
"""

from __future__ import annotations

import hashlib

from personaljarvis.contacts.sync.audit import container_ref

__all__ = ["account_ref", "container_ref", "provider_type",
           "PROVIDER_TYPE_UNKNOWN"]

#: Gattungsname, wenn ein Konto keiner bekannten Providerart zugeordnet ist.
#: Bewusst ein fester Wert und **kein** Teilstring der Kennung: eine Heuristik
#: über Präfixe würde genau das durchreichen, was hier verschwinden soll.
PROVIDER_TYPE_UNKNOWN = "unknown"

#: Exakte Zuordnung Kontokennung → stabile Gattung. Der Schlüssel ist der Wert
#: aus `live.APPLE_PROVIDER_ACCOUNT`; die Tabelle wächst mit jedem weiteren
#: Provider, nie mit einem Muster.
_PROVIDER_TYPES = {"apple-local": "apple_contacts"}


def account_ref(identifier: str) -> str:
    """Deterministisches, nicht zurückrechenbares Kürzel einer Kontokennung."""
    return "A-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:6]


def provider_type(provider_account_id: str) -> str:
    """Stabile Gattungsbezeichnung eines Providerkontos."""
    return _PROVIDER_TYPES.get(provider_account_id, PROVIDER_TYPE_UNKNOWN)

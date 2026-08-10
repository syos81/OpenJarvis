"""Migration 0011 — identitätsfreier Zustandsdigest (Eigentümer: `calendar`).

Block B3 P3 braucht für die Herkunftskontinuität ZWEI getrennte Bindungen
(verbindliche Eigentümerentscheidung): die Identitätsbindung über die real
gespeicherten Provider-Identifier und — davon unabhängig — eine Bindung des
rein fachlichen Zustands.

Warum eine neue Spalte und nicht der vorhandene `readback_digest`: dieser
deckt die sieben Vertragsfelder **plus** `provider_calendar_id`. Er ist damit
gerade nicht identitätsfrei, und eine Identitätsänderung könnte in ihm eine
Zustandsänderung verdecken. `semantic_state_digest` deckt ausschliesslich die
sieben Felder; beide Aussagen bleiben getrennt prüfbar.

Die Spalte ist nullbar, weil eine veröffentlichte Migration unveränderlich
ist und die bereits gesettelten historischen Zeilen sie nicht tragen können.
`NULL` heisst deshalb ausdrücklich **nicht** „unverändert", sondern „für
diese Zeile nicht rekonstruierbar" — und führt in der Herkunftsprüfung zu
`semantic_state_binding_missing`, also zu blockiert, nie zu einem stillen
Bestehen.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE calendar_mutations ADD COLUMN semantic_state_digest TEXT",
)

MIGRATION = Migration(
    migration_id="0011",
    module_owner="calendar",
    description="Identitaetsfreier Zustandsdigest der Kalender-Mutationslinie",
    statements=_STATEMENTS,
    schema_version=11,
    depends_on=("0010",),
)

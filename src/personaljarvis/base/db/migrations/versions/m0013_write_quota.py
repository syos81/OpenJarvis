"""Migration 0013 — Kontingent je Schreibfreigabe (Eigentümer: `contacts`).

Eine Dauerfreigabe gilt, bis der Eigentümer sie zurücknimmt. Gemessen am
2026-08-17 liefen unter einer einzigen Freigabe 25 von 25 Mutationen
nacheinander durch, ohne Begrenzung pro Vorgang, Zeitraum oder Sitzung. Die
strukturelle Reparatur (Belegpflicht) macht jede einzelne Freigabe zu einer
Eigentümerhandlung; das Kontingent begrenzt zusätzlich, wie viele davon eine
Aktivierung überhaupt tragen kann.

**Warum eine Zeile je Mutation und kein Zähler.** Ein Zähler müsste beim
technischen Wiederholungsversuch derselben Mutation wissen, dass er schon
gezählt hat — eine Regel, die man vergessen kann. Der Primärschlüssel aus
Aktivierung und Mutation kann es nicht: Ein zweiter Beanspruchungsversuch
derselben Mutation trifft dieselbe Zeile und verbraucht nichts. Idempotenz
aus dem Schema statt aus Disziplin.

`activation_id` ist der Fingerabdruck der geltenden Freigabeurkunde. Nimmt der
Eigentümer sie zurück und erteilt sie neu — was eine Systemauthentifizierung
verlangt —, entsteht eine andere Urkunde, also eine andere Aktivierung und
damit ein frisches Kontingent. Ohne diese Bindung wäre „neues Kontingent" eine
Zurücksetzung, und eine Zurücksetzung könnte jeder auslösen.

Die Zeile trägt keine Kontaktdaten: Aktivierung, Mutationskennung, Zeitpunkt.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration

__all__ = ["MIGRATION"]

_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE contacts_write_quota (
        activation_id TEXT NOT NULL,
        mutation_id   TEXT NOT NULL,
        claimed_at    TEXT NOT NULL,
        PRIMARY KEY (activation_id, mutation_id),
        CHECK (activation_id <> ''),
        CHECK (mutation_id <> '')
    ) STRICT
    """,
    "CREATE INDEX ix_write_quota_activation ON contacts_write_quota "
    "(activation_id)",
)

MIGRATION = Migration(
    migration_id="0013",
    module_owner="contacts",
    description="Kontingent beanspruchter Mutationen je Schreibfreigabe",
    statements=_STATEMENTS,
    schema_version=13,
    depends_on=("0012",),
)

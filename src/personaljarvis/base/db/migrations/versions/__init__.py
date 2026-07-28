"""Geordnete, unveränderliche Migrationsliste (07 §6).

Die Reihenfolge in `ALL_MIGRATIONS` ist die Ausführungsreihenfolge. Eine
veröffentlichte Migration wird **nie** geändert — eine Korrektur ist eine neue
Migration mit höherer ID.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration
from personaljarvis.base.db.migrations.versions.m0001_base import MIGRATION as M0001
from personaljarvis.base.db.migrations.versions.m0002_contacts import MIGRATION as M0002

__all__ = ["ALL_MIGRATIONS"]

ALL_MIGRATIONS: tuple[Migration, ...] = (M0001, M0002)

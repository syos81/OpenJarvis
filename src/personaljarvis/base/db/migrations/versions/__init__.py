"""Geordnete, unveränderliche Migrationsliste (07 §6).

Die Reihenfolge in `ALL_MIGRATIONS` ist die Ausführungsreihenfolge. Eine
veröffentlichte Migration wird **nie** geändert — eine Korrektur ist eine neue
Migration mit höherer ID.
"""

from __future__ import annotations

from personaljarvis.base.db.migrations.ledger import Migration
from personaljarvis.base.db.migrations.versions.m0001_base import MIGRATION as M0001
from personaljarvis.base.db.migrations.versions.m0002_contacts import MIGRATION as M0002
from personaljarvis.base.db.migrations.versions.m0003_contacts_child_constraints import (
    MIGRATION as M0003,
)
from personaljarvis.base.db.migrations.versions.m0004_mutation_pipeline import (
    MIGRATION as M0004,
)
from personaljarvis.base.db.migrations.versions.m0005_sync_audit import (
    MIGRATION as M0005,
)
from personaljarvis.base.db.migrations.versions.m0006_provider_applied import (
    MIGRATION as M0006,
)
from personaljarvis.base.db.migrations.versions.m0007_manual_resolution import (
    MIGRATION as M0007,
)
from personaljarvis.base.db.migrations.versions.m0008_app_process_channel import (
    MIGRATION as M0008,
)
from personaljarvis.base.db.migrations.versions.m0009_calendar import (
    MIGRATION as M0009,
)
from personaljarvis.base.db.migrations.versions.m0010_calendar_mutations import (
    MIGRATION as M0010,
)
from personaljarvis.base.db.migrations.versions.m0011_calendar_semantic_state import (
    MIGRATION as M0011,
)
from personaljarvis.base.db.migrations.versions.m0012_container_name import (
    MIGRATION as M0012,
)

__all__ = ["ALL_MIGRATIONS"]

ALL_MIGRATIONS: tuple[Migration, ...] = (M0001, M0002, M0003, M0004, M0005,
                                          M0006, M0007, M0008, M0009, M0010,
                                          M0011, M0012)

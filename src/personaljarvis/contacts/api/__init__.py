"""HTTP-Schicht des Kontakte-Moduls (Plan §9.2).

Der Import dieses Pakets hat keine Nebenwirkung: der Router entsteht erst
durch `create_contacts_router(module)` über einem gestarteten Modul.
"""

from __future__ import annotations

from personaljarvis.contacts.api.routes import (
    DEFAULT_WORKSPACE_HEADER,
    PREFIX,
    create_contacts_router,
)

__all__ = ["PREFIX", "DEFAULT_WORKSPACE_HEADER", "create_contacts_router"]

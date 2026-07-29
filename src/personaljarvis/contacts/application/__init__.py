"""Application-Schicht des Kontakte-Moduls — der eine Schreibpfad (05, AV-35)."""

from __future__ import annotations

from personaljarvis.contacts.application.approvals import (
    ContactsApprovalService,
    PendingApproval,
)
from personaljarvis.contacts.application.command_bus import (
    CONTACT_COMMANDS,
    register_contacts_commands,
)
from personaljarvis.contacts.application.commands import (
    ContactDraft,
    ContactPatch,
    CreateContact,
    DeleteContact,
    UpdateContact,
)
from personaljarvis.contacts.application.models import (
    ExecutionResult,
    MutationPayload,
    MutationPreview,
    PreparedMutation,
    ProviderOutcome,
    ReconcileResult,
    ReconcileVerdict,
    SendPhase,
)
from personaljarvis.contacts.application.mutation_service import (
    ContactsMutationService,
    MutationProvider,
    MutationState,
    ProviderResponse,
)
from personaljarvis.contacts.application.reconcile import (
    ContactsReconcileService,
    ReconcileObservation,
    ReconcileReader,
)

__all__ = [
    "CONTACT_COMMANDS", "ContactDraft", "ContactPatch", "ContactsApprovalService",
    "ContactsMutationService", "ContactsReconcileService", "CreateContact",
    "DeleteContact", "ExecutionResult", "MutationPayload", "MutationPreview",
    "MutationProvider", "MutationState", "PendingApproval", "PreparedMutation",
    "ProviderOutcome", "ProviderResponse", "ReconcileObservation",
    "ReconcileReader", "ReconcileResult", "ReconcileVerdict", "SendPhase",
    "UpdateContact", "register_contacts_commands",
]

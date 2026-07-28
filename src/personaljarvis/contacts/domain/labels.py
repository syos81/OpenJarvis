"""Egress-Labels der Kontaktfelder (12 §1).

Das Modul registriert für seine Entitätstypen ein Feld-Label-Schema; die
Durchsetzung ist Aufgabe des EgressGuard und des ModelPort. Die Labels sind
**getrennt** von den Rohlabels des Providers (`label_raw`) — ein Provider-Label
wie „privat" sagt nichts über die Sensitivität aus.
"""

from __future__ import annotations

from personaljarvis.contacts.domain.enums import SensitivityLabel

__all__ = ["FIELD_LABELS", "label_for", "ENTITY_TYPE"]

ENTITY_TYPE = "contact"

# S0 — unkritisch · S1 — personenbezogen · S2 — besonders schutzwürdig
FIELD_LABELS: dict[str, SensitivityLabel] = {
    "id": SensitivityLabel.S0,
    "workspace_id": SensitivityLabel.S0,
    "contact_type": SensitivityLabel.S0,
    "display_name": SensitivityLabel.S1,
    "given_name": SensitivityLabel.S1,
    "middle_name": SensitivityLabel.S1,
    "family_name": SensitivityLabel.S1,
    "previous_family_name": SensitivityLabel.S2,
    "name_prefix": SensitivityLabel.S1,
    "name_suffix": SensitivityLabel.S1,
    "phonetic_given_name": SensitivityLabel.S1,
    "phonetic_family_name": SensitivityLabel.S1,
    "nickname": SensitivityLabel.S1,
    "organization_name": SensitivityLabel.S1,
    "department_name": SensitivityLabel.S1,
    "job_title": SensitivityLabel.S1,
    "emails": SensitivityLabel.S2,
    "phones": SensitivityLabel.S2,
    "postal_addresses": SensitivityLabel.S2,
    "birthday": SensitivityLabel.S2,
    "dates": SensitivityLabel.S2,
    "urls": SensitivityLabel.S1,
    "social_profiles": SensitivityLabel.S2,
    "instant_messages": SensitivityLabel.S2,
    "relations": SensitivityLabel.S2,
    "roles": SensitivityLabel.S1,
    "thumbnail_blob_ref": SensitivityLabel.S2,
    "is_me_card": SensitivityLabel.S1,
    "external_ids": SensitivityLabel.S2,
}


def label_for(field_name: str) -> SensitivityLabel:
    """Unbekannte Felder gelten fail-closed als S2 — nie als harmlos."""
    return FIELD_LABELS.get(field_name, SensitivityLabel.S2)

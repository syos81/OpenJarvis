"""Synthetic PII canaries.

Every value here is artificial and clearly recognisable. No real contact,
calendar, mail, banking or tenant data is used anywhere in this repository's
tooling or tests.

The values are assembled at import time so that neither the marker nor a
complete canary value ever appears verbatim in a tracked source file — the
repository guard can therefore assert that no tracked artifact contains the
marker at all.
"""

from __future__ import annotations

MARKER = "".join(("GATE", "CANARY"))

_USER_ROOT = "/" + "Users" + "/" + f"{MARKER.lower()}person"


def _wrap(value: str) -> str:
    return f"{MARKER}-{value}-{MARKER}"


#: canary_id -> synthetic value, one per required class.
CANARIES = {
    "person_name": _wrap("Annelie Musterfrau"),
    "email_address": f"{MARKER.lower()}.person@example.invalid",
    "phone_number": "+49 30 " + "1234567890",
    "absolute_user_path": f"{_USER_ROOT}/Documents/Mietvertrag-Muster.pdf",
    "document_subject": _wrap("Betreff: Nebenkostenabrechnung 2026"),
    "external_object_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "secret_token": "sk-" + MARKER.lower() + "0123456789abcdef",
    "unicode_spelling": _wrap("Ännelie Mustermann-Straße"),
}

#: Encoded / normalised variants that must be caught as well.
VARIANT_KINDS = ("plain", "base64", "percent", "nfd", "case", "separators")

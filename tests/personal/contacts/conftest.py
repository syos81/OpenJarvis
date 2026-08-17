"""Gemeinsame Fixtures der Gate-A-Suite.

**Kontaktfrei:** Kein Test dieser Suite startet einen Sidecar, fragt TCC ab,
berührt `CNContactStore` oder liest einen echten Kontakt. Alle Daten sind
erfundene Fixtures; alle Datenbanken liegen in `tmp_path` oder im Speicher.
"""

from __future__ import annotations

import uuid

import pytest

from personaljarvis.base.db.factory import ConnectionFactory
from personaljarvis.base.db.migrations import ALL_MIGRATIONS, MigrationRunner
from personaljarvis.base.db.unit_of_work import UnitOfWork
from personaljarvis.contacts.domain.enums import (
    ContactType,
    FieldAvailabilityState,
)
from personaljarvis.contacts.domain.models import (
    Contact,
    ContactFieldAvailability,
    EmailAddress,
    PhoneNumber,
)
from personaljarvis.contacts.lifecycle import ContactsModule

WORKSPACE = "ws-test"


def new_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "personal" / "jarvis.db"


@pytest.fixture
def factory(db_path) -> ConnectionFactory:
    f = ConnectionFactory(db_path)
    f.ensure_ready()
    yield f
    f.close()


@pytest.fixture
def migrated_factory(factory) -> ConnectionFactory:
    MigrationRunner(factory, ALL_MIGRATIONS).run()
    return factory


@pytest.fixture
def uow(migrated_factory):
    with UnitOfWork(migrated_factory) as unit:
        yield unit


@pytest.fixture
def module(db_path) -> ContactsModule:
    m = ContactsModule(db_path)
    m.start()
    yield m
    m.stop()


def make_contact(**overrides) -> Contact:
    """Ein vollständig gefüllter Fixture-Kontakt — rein erfunden."""
    cid = overrides.pop("id", new_id())
    defaults = dict(
        id=cid,
        workspace_id=WORKSPACE,
        contact_type=ContactType.PERSON,
        display_name="Fixture Eins",
        given_name="Fixture",
        family_name="Eins",
        emails=(
            EmailAddress(
                id=new_id(), position=0, label_raw="_$!<Work>!$_",
                label_normalized="work", value_raw="eins@example.invalid",
                value_normalized="eins@example.invalid",
            ),
        ),
        phones=(
            PhoneNumber(
                id=new_id(), position=0, label_raw="_$!<Mobile>!$_",
                label_normalized="mobile", value_raw="+49 30 000000",
                value_normalized_e164="+4930000000",
            ),
        ),
        field_availability=(
            ContactFieldAvailability(
                field_name="note",
                state=FieldAvailabilityState.UNAVAILABLE_BY_CAPABILITY,
            ),
        ),
    )
    defaults.update(overrides)
    return Contact(**defaults)


@pytest.fixture(autouse=True)
def eigentuemerbeleg_vorhanden(monkeypatch):
    """Diese Suite prüft den Ablauf **nach** der Freigabe, nicht ihre Herkunft.

    Seit der Reparatur vom 2026-08-17 entsteht eine Eigentümerentscheidung nur
    gegen einen Beleg aus dem App-Prozess (`base/owner_attestation.py`). Ohne
    diese Öffnung käme in dieser Suite keine einzige Freigabe mehr zustande und
    rund achtzig Prüfungen zu Verbrauch, Zuständen, Fingerprintbindung und
    Nebenläufigkeit wären stumm.

    Die Annahme steht deshalb hier sichtbar. Die Herkunft selbst prüft
    `test_owner_provenance.py` — dort ausdrücklich **ohne** diese Öffnung.
    """
    from personaljarvis.base import owner_attestation as beleg

    def _immer(*, capability, mutation_id, payload_digest, preview_digest,
               **_):
        return beleg.OwnerAttestation(
            capability=capability, mutation_id=mutation_id,
            payload_digest=payload_digest, preview_digest=preview_digest,
            attested_at="2026-08-17T12:00:00Z", method="testannahme")

    monkeypatch.setattr(beleg, "read_attestation", _immer)
    monkeypatch.setattr(beleg, "consume_attestation", lambda **_: True)

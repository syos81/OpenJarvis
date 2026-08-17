"""Die Herkunft der Eigentümerentscheidung — ohne jede Testannahme.

Diese Datei liegt bewusst **neben** den Modulsuiten und nicht in ihnen: Deren
`conftest.py` öffnet den Belegweg, damit die Prüfungen nach der Freigabe nicht
stumm werden. Hier gilt genau das nicht.

Gemessener Ausgangsbefund vom 2026-08-17: Ein `POST` auf
`/mutations/{id}/approve` mit frei gesetztem `decision_actor` erzeugte eine
gültige Eigentümerentscheidung, und 25 von 25 Mutationen liefen so nacheinander
durch. Der Name im Aufruf wurde als Authentizitätsbeweis gelesen. Diese Datei
prüft, dass das nicht mehr geht.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from personaljarvis.base.approvals import (
    SelfApprovalRejected,
    owner_decision_attested,
    owner_decision_for_tests,
)
from personaljarvis.base.owner_attestation import (
    ATTESTATION_CONTRACT,
    OwnerAttestation,
    consume_attestation,
    read_attestation,
)

#: Die echte Uhr, nicht ein fester Zeitpunkt: `owner_decision_attested()` liest
#: absichtlich die Systemzeit — ein Beleg ist frisch oder er ist keiner, und
#: ein Testparameter dafür wäre genau die Lücke, die er schliessen soll.
JETZT = datetime.now(timezone.utc)
MUTATION = "11111111-1111-4111-8111-111111111111"
DIGEST = "a" * 64


@pytest.fixture
def belegordner(tmp_path):
    ordner = tmp_path / "owner-approvals"
    ordner.mkdir()
    os.chmod(ordner, 0o700)
    return ordner


def beleg_schreiben(ordner, *, mutation_id=MUTATION, payload_digest=DIGEST,
                    capability="contacts", modus=0o600, **rest):
    dokument = {
        "contract": ATTESTATION_CONTRACT,
        "capability": capability,
        "mutation_id": mutation_id,
        "payload_digest": payload_digest,
        "attested_at": JETZT.isoformat(),
        "method": "device_owner_authentication",
    }
    dokument.update(rest)
    datei = ordner / f"{mutation_id}.json"
    datei.write_text(json.dumps(dokument), encoding="utf-8")
    os.chmod(datei, modus)
    return datei


# ── Der Kern der Reparatur ───────────────────────────────────────────────────
def test_ein_freier_name_erzeugt_keine_eigentuemerentscheidung(belegordner):
    """Genau der Aufruf, der bisher genügte: ein Name, sonst nichts."""
    with pytest.raises(SelfApprovalRejected):
        owner_decision_attested(
            capability="contacts", mutation_id=MUTATION,
            payload_digest=DIGEST, actor="lukas", verzeichnis=belegordner)


def test_mit_beleg_entsteht_die_entscheidung(belegordner):
    beleg_schreiben(belegordner)
    entscheidung = owner_decision_attested(
        capability="contacts", mutation_id=MUTATION, payload_digest=DIGEST,
        actor="lukas", verzeichnis=belegordner)
    assert entscheidung.actor == "lukas"


def test_ein_beleg_traegt_genau_eine_mutation(belegordner):
    """Eine Handlung, eine Mutation. Das ist die Schranke gegen die Schleife."""
    beleg_schreiben(belegordner)
    owner_decision_attested(
        capability="contacts", mutation_id=MUTATION, payload_digest=DIGEST,
        actor="lukas", verzeichnis=belegordner)
    # Der zweite Versuch findet nichts mehr — der Beleg ist verbraucht.
    with pytest.raises(SelfApprovalRejected):
        owner_decision_attested(
            capability="contacts", mutation_id=MUTATION,
            payload_digest=DIGEST, actor="lukas", verzeichnis=belegordner)


def test_ein_beleg_gilt_nicht_fuer_einen_anderen_vorgang(belegordner):
    beleg_schreiben(belegordner)
    fremd = "22222222-2222-4222-8222-222222222222"
    with pytest.raises(SelfApprovalRejected):
        owner_decision_attested(
            capability="contacts", mutation_id=fremd, payload_digest=DIGEST,
            actor="lukas", verzeichnis=belegordner)


def test_eine_nach_der_handlung_geaenderte_nutzlast_bricht_den_beleg(belegordner):
    """Freigegeben wurde, was angezeigt wurde — nicht, was danach kam."""
    beleg_schreiben(belegordner)
    with pytest.raises(SelfApprovalRejected):
        owner_decision_attested(
            capability="contacts", mutation_id=MUTATION,
            payload_digest="b" * 64, actor="lukas", verzeichnis=belegordner)


def test_ein_beleg_gilt_nicht_fuer_eine_andere_faehigkeit(belegordner):
    beleg_schreiben(belegordner, capability="contacts")
    with pytest.raises(SelfApprovalRejected):
        owner_decision_attested(
            capability="calendar", mutation_id=MUTATION,
            payload_digest=DIGEST, actor="lukas", verzeichnis=belegordner)


# ── Die Dateibedingungen ─────────────────────────────────────────────────────
def test_ein_zu_offener_beleg_gilt_nicht(belegordner):
    beleg_schreiben(belegordner, modus=0o644)
    assert read_attestation(capability="contacts", mutation_id=MUTATION,
                            payload_digest=DIGEST, verzeichnis=belegordner,
                            jetzt=JETZT) is None


def test_ein_beleg_in_einem_offenen_ordner_gilt_nicht(belegordner):
    beleg_schreiben(belegordner)
    os.chmod(belegordner, 0o755)
    try:
        assert read_attestation(capability="contacts", mutation_id=MUTATION,
                                payload_digest=DIGEST,
                                verzeichnis=belegordner, jetzt=JETZT) is None
    finally:
        os.chmod(belegordner, 0o700)


def test_ein_alter_beleg_gilt_nicht(belegordner):
    beleg_schreiben(belegordner)
    spaeter = JETZT + timedelta(minutes=20)
    assert read_attestation(capability="contacts", mutation_id=MUTATION,
                            payload_digest=DIGEST, verzeichnis=belegordner,
                            jetzt=spaeter) is None


def test_ein_beleg_aus_der_zukunft_gilt_nicht(belegordner):
    beleg_schreiben(belegordner,
                    attested_at=(JETZT + timedelta(minutes=5)).isoformat())
    assert read_attestation(capability="contacts", mutation_id=MUTATION,
                            payload_digest=DIGEST, verzeichnis=belegordner,
                            jetzt=JETZT) is None


def test_ein_fremder_vertrag_gilt_nicht(belegordner):
    beleg_schreiben(belegordner, contract="owner-approval-v0")
    assert read_attestation(capability="contacts", mutation_id=MUTATION,
                            payload_digest=DIGEST, verzeichnis=belegordner,
                            jetzt=JETZT) is None


def test_eine_kennung_kann_nicht_aus_dem_ordner_ausbrechen(belegordner):
    """Die Kennung landet in einem Dateinamen — also wird sie eingeschränkt,
    nicht bereinigt."""
    for boese in ["../andere", "a/b", "a.b", ""]:
        assert read_attestation(capability="contacts", mutation_id=boese,
                                payload_digest=DIGEST,
                                verzeichnis=belegordner, jetzt=JETZT) is None
        assert consume_attestation(mutation_id=boese,
                                   verzeichnis=belegordner) is False


# ── Der Testweg bleibt ein Testweg ───────────────────────────────────────────
def test_der_testweg_baut_weiterhin_eine_entscheidung():
    """Er darf das — er steht in keiner Produktdatei (Statiktest in
    `contacts/test_owner_grant.py`)."""
    assert owner_decision_for_tests("lukas").actor == "lukas"


def test_ein_maschineller_ursprung_entscheidet_nie(belegordner):
    beleg_schreiben(belegordner)
    for maschine in ("automation", "llm_assisted", "system"):
        with pytest.raises(SelfApprovalRejected):
            owner_decision_attested(
                capability="contacts", mutation_id=MUTATION,
                payload_digest=DIGEST, actor=maschine,
                verzeichnis=belegordner)


def test_der_beleg_traegt_sein_verfahren(belegordner):
    beleg_schreiben(belegordner)
    beleg = read_attestation(capability="contacts", mutation_id=MUTATION,
                             payload_digest=DIGEST, verzeichnis=belegordner,
                             jetzt=JETZT)
    assert isinstance(beleg, OwnerAttestation)
    assert beleg.method == "device_owner_authentication"

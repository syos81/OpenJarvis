"""Die Capability-Brücke im produktiven Aufbau (`attach`). **Kontaktfrei.**

Der Sidecar ist hier ein winziges Shell-Skript, das die `ready`-Zeile und eine
`pong`-Antwort schreibt — mehr braucht der Startcheck nicht. Es gibt keinen
`CNContactStore`, keine Autorisierung und keinen Dialog; das Skript kann
Kontakte gar nicht erreichen.

Geprüft wird die Kette, die vor der Korrektur nicht geschlossen war:

    Handshake → BridgeStatus → ContactCapabilitySet → MutationService

Ohne sie blieb `create_supported` dauerhaft `False`, und die Brücke aus
`derive_capabilities` hatte produktiv keinen Aufrufer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import personaljarvis
from personaljarvis.contacts.bridge import protocol

_REPO = Path(__file__).resolve().parents[3]

#: Vollständig kompatibler Handshake — dieselben Vertragsversionen wie der Kern.
KOMPATIBEL = {
    "notesSupported": False, "linkUnlinkSupported": False,
    "unifiedReadOnly": True, "meCardReadOnly": True,
    "changeHistorySupported": True, "fullDiffFallbackSupported": True,
    "mutationsImplemented": True, "createImplemented": True,
    "updateImplemented": False, "deleteImplemented": False,
    "mutationContractVersion": protocol.MUTATION_CONTRACT_VERSION,
    "fieldContractVersion": protocol.FIELD_CONTRACT_VERSION,
}


class AppAttrappe:
    def __init__(self) -> None:
        self.state = type("S", (), {})()

    def include_router(self, router) -> None:
        pass

    def on_event(self, name):
        return lambda f: f


def _sidecar_skript(tmp_path: Path, capabilities: dict | None) -> Path:
    """Ein Skript, das den Handshake spricht — und sonst nichts kann.

    Es beantwortet ausschliesslich `ping` und beendet sich bei `shutdown`
    bzw. bei EOF. Ein Store-Zugriff ist ihm strukturell unmöglich.
    """
    from personaljarvis.contacts.bridge.resolver import BINARY_NAME

    ready = {
        "type": "ready", "protocolVersion": protocol.PROTOCOL_VERSION,
        "bundleIdentifier": "de.kluender.jarvis.contacts-bridge",
        "transactionAuthor": "de.kluender.jarvis.contacts-bridge",
        "keySetVersion": 1, "authorizationStatus": "authorized",
        "operations": ["ping", "caps", "shutdown"],
    }
    if capabilities is not None:
        ready["capabilities"] = capabilities
    pfad = tmp_path / BINARY_NAME
    pfad.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{json.dumps(ready, sort_keys=True)}'\n"
        "while IFS= read -r zeile; do\n"
        "  case \"$zeile\" in\n"
        "    *shutdown*) printf '%s\\n' '{\"protocolVersion\":1,\"requestId\":1,"
        "\"ok\":true,\"result\":{\"bye\":true}}'; exit 0 ;;\n"
        "    *) printf '%s\\n' '{\"protocolVersion\":1,\"requestId\":1,"
        "\"ok\":true,\"result\":{\"pong\":true}}' ;;\n"
        "  esac\n"
        "done\n")
    pfad.chmod(0o755)
    return pfad


def _freigabe_legen(ordner):
    """Eine gueltige, kurz laufende Schreibfreigabe — synthetisch."""
    import json
    import os
    from datetime import datetime, timedelta, timezone

    from personaljarvis.contacts.application.write_release import (
        WRITE_RELEASE_CONTRACT,
        WRITE_RELEASE_FILENAME,
    )
    ordner.mkdir(parents=True, exist_ok=True)
    os.chmod(ordner, 0o700)
    pfad = ordner / WRITE_RELEASE_FILENAME
    pfad.write_text(json.dumps({
        "contract": WRITE_RELEASE_CONTRACT,
        "operations": ["create"],
        "expires_at": (datetime.now(timezone.utc)
                       + timedelta(hours=1)).isoformat(),
        "reason": "kontaktfreier Capability-Test",
    }), encoding="utf-8")
    os.chmod(pfad, 0o600)
    return pfad


@pytest.fixture
def aufbau(tmp_path, db_path, monkeypatch):
    """Baut das Modul über `attach` auf — wie im produktiven Serverstart."""
    import personaljarvis.contacts.bridge.resolver as resolver

    # Die Architekturpruefung greift bei einem Shell-Skript nicht; der
    # Aufloesungsweg selbst bleibt der produktive.
    monkeypatch.setattr(resolver, "binary_architectures",
                        lambda p: (resolver.host_architecture(),))

    gebaut = []

    def bauen(capabilities: dict | None, *, sidecar: bool = True,
              schreibfreigabe: bool = True):
        """Baut das Modul auf.

        `schreibfreigabe` legt die 0600-Freigabedatei neben die Datenbank.
        Seit ADR-0020 §10 kommt das Create-Recht aus dem App-Prozess-Kanal
        und nicht mehr aus dem Sidecar-Handshake; ohne Freigabe waere
        `create_supported` deshalb immer falsch, und die Tests dieser Datei
        prueften nur noch eine Konstante.
        """
        if schreibfreigabe:
            _freigabe_legen(db_path.parent)
        app = AppAttrappe()
        pfad = (_sidecar_skript(tmp_path, capabilities) if sidecar
                else tmp_path / "gibt-es-nicht")
        runtime = personaljarvis.attach(
            app, database_path=str(db_path),
            lock_path=str(tmp_path / "l.lock"), sidecar_path=str(pfad))
        gebaut.append(app)
        return runtime

    yield bauen
    for app in gebaut:
        app.state.personal_bootstrap.stop()


# ═══ Freischaltung ══════════════════════════════════════════════════════════
def test_kompatibler_vertragsstand_und_freigabe_schalten_create_frei(aufbau):
    """Beides zusammen — der Sidecar allein schaltet seit ADR-0020 nichts."""
    caps = aufbau(KOMPATIBEL).contacts.capabilities
    assert caps.create_supported is True
    assert caps.read_supported is True


def test_update_und_delete_bleiben_gesperrt(aufbau):
    caps = aufbau(KOMPATIBEL).contacts.capabilities
    assert caps.update_supported is False
    assert caps.delete_supported is False


def test_der_mutationsdienst_sieht_dieselben_faehigkeiten(aufbau):
    """Der Dienst wird beim Start fuer die Erholung schon einmal gebaut.

    Vor der Korrektur haette er die alte Menge festgehalten und `create` waere
    auch bei kompatiblem Sidecar gesperrt geblieben.
    """
    contacts = aufbau(KOMPATIBEL).contacts
    dienst = contacts.mutation_service()
    assert dienst._capabilities is contacts.capabilities
    assert dienst._capabilities.create_supported is True


def test_die_faehigkeiten_erreichen_den_api_vertrag(aufbau):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from personaljarvis.contacts.api.routes import (
        DEFAULT_WORKSPACE_HEADER,
        PREFIX,
        create_contacts_router,
    )

    contacts = aufbau(KOMPATIBEL).contacts
    app = FastAPI()
    app.include_router(create_contacts_router(contacts))
    body = TestClient(app).get(
        f"{PREFIX}/capabilities",
        headers={DEFAULT_WORKSPACE_HEADER: "default"}).json()
    assert body["create_supported"] is True
    assert body["update_supported"] is False
    assert body["delete_supported"] is False
    assert body["mutations_available"] is True


# ═══ Fail-closed in jeder Richtung ══════════════════════════════════════════
def test_ohne_schreibfreigabe_bleibt_create_gesperrt(aufbau):
    """Der Kanal ist zu — und damit `create`, egal was der Sidecar meldet."""
    caps = aufbau(KOMPATIBEL, schreibfreigabe=False).contacts.capabilities
    assert caps.create_supported is False
    assert caps.read_supported is True


def test_fehlender_sidecar_schaltet_nichts_frei(aufbau):
    caps = aufbau(None, sidecar=False).contacts.capabilities
    assert caps.create_supported is False
    assert caps.read_supported is True


def test_handshake_ohne_capabilities_schaltet_nichts_frei(aufbau):
    caps = aufbau(None).contacts.capabilities
    assert caps.create_supported is False


@pytest.mark.parametrize("abweichung", [
    {"mutationContractVersion": protocol.MUTATION_CONTRACT_VERSION - 1},
    {"mutationContractVersion": protocol.MUTATION_CONTRACT_VERSION + 1},
    {"fieldContractVersion": protocol.FIELD_CONTRACT_VERSION + 1},
])
def test_fremder_vertragsstand_schaltet_nichts_frei(aufbau, abweichung):
    caps = aufbau({**KOMPATIBEL, **abweichung}).contacts.capabilities
    assert caps.create_supported is False


@pytest.mark.parametrize("fehlend", ["mutationContractVersion",
                                     "fieldContractVersion"])
def test_fehlende_versionsangabe_schaltet_nichts_frei(aufbau, fehlend):
    caps = aufbau({k: v for k, v in KOMPATIBEL.items()
                   if k != fehlend}).contacts.capabilities
    assert caps.create_supported is False


def test_das_sidecar_flag_entscheidet_nicht_mehr_ueber_create(aufbau):
    """Seit ADR-0020 §10 ist `createImplemented` fuer Schreibrechte belanglos.

    Der Sidecar hat gar keinen Schreibpfad mehr und meldet das Flag dauerhaft
    falsch; wuerde es weiterhin zaehlen, waere `create` fuer immer gesperrt.
    Entscheidend sind Vertragsstand und App-Prozess-Kanal — beide liegen hier
    vor, also ist `create` frei, obwohl der Sidecar `false` meldet.
    """
    caps = aufbau({**KOMPATIBEL,
                   "createImplemented": False}).contacts.capabilities
    assert caps.create_supported is True
    # Update und Delete bleiben davon unberuehrt.
    assert caps.update_supported is False
    assert caps.delete_supported is False


# ═══ Der Startcheck selbst ══════════════════════════════════════════════════
def test_der_startcheck_ist_kontaktfrei():
    """Statisch: `check_bridge` sendet nur kontaktfreie Operationen."""
    import inspect

    from personaljarvis.contacts import lifecycle

    quelle = inspect.getsource(lifecycle.ContactsModule.check_bridge)
    code = "\n".join(z.split("#", 1)[0] for z in quelle.splitlines())
    for verboten in ("CONTAINERS", "ENUMERATE", "CHANGES", "Operation.GET",
                     "REQUEST_AUTHORIZATION", "AUTHORIZATION_STATUS",
                     "CNContactStore"):
        assert verboten not in code, verboten
    # Genau eine Anfrage, und die ist `ping`.
    assert code.count("process.request(") == 1
    assert "Operation.PING" in code


def test_der_aufbau_fuehrt_nichts_aus(aufbau):
    """`attach` bereitet nichts vor, gibt nichts frei und sendet nichts."""
    contacts = aufbau(KOMPATIBEL).contacts
    with contacts.unit_of_work() as uow:
        for tabelle in ("contacts_mutations", "personal_approvals",
                        "personal_external_action_outbox"):
            anzahl = uow.execute(f"SELECT COUNT(*) c FROM {tabelle}").fetchone()
            assert anzahl["c"] == 0, tabelle


def test_die_aufrufreihenfolge_steht_im_quelltext():
    """Der Startcheck muss **vor** der Registrierung laufen."""
    import inspect

    quelle = inspect.getsource(personaljarvis.attach)
    assert (quelle.index("_derive_capabilities(")
            < quelle.index("_register_mutation_bridge(")), (
        "Der Handshake muss vor der Registrierung ausgewertet werden, sonst "
        "traegt der neu gebaute Dienst die alte Faehigkeitsmenge")

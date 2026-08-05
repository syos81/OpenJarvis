"""Strukturelle Grenzen des Kalendermoduls.

Diese Tests prüfen Zusagen, die man sonst nur behaupten könnte: dass v1
nicht schreibt, dass die Berechtigung nur auf Nutzeraktion angefragt wird,
dass es keine zweite Sidecar-Infrastruktur gibt und dass beide
Usage-Description-Schlüssel samt Entitlement vorhanden sind.

Alle Prüfungen sind **kalenderfrei** — sie lesen Quelltext und Konfiguration,
nie einen Kalender.
"""

from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CALENDAR_SRC = REPO_ROOT / "src/personaljarvis/calendar"
SIDECAR_SWIFT = REPO_ROOT / "native/calendar-bridge/src/sidecar.swift"
BUILD_SH = REPO_ROOT / "native/calendar-bridge/build.sh"
TAURI = REPO_ROOT / "frontend/src-tauri"


def _python_code_ohne_prosa(path: Path) -> str:
    """Python-Quelltext ohne Kommentare und Zeichenkettenliterale.

    Die Verbote stehen als Kommentar oder Docstring IM Produktivcode ("kein
    Schreiben"). Eine reine Textsuche würde genau diese Abgrenzungsnotizen als
    Verstoss melden. Geprüft wird deshalb ausschliesslich echter Code.
    """
    out: list[str] = []
    for tok in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
        if tok.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        out.append(tok.string)
    return " ".join(out)


def _swift_ohne_prosa(text: str) -> str:
    """Swift ohne Zeilenkommentare und Zeichenkettenliterale."""
    zeilen = []
    for zeile in text.splitlines():
        ohne_kommentar = zeile.split("//", 1)[0]
        # Zeichenkettenliterale entfernen (einfache Naeherung, genuegt hier).
        teile = ohne_kommentar.split('"')
        zeilen.append("".join(teile[::2]))
    return "\n".join(zeilen)


# ── v1 schreibt nicht ────────────────────────────────────────────────────────
def test_der_sidecar_enthaelt_keinen_eventkit_schreibaufruf():
    """Die erste von zwei Prüfungen: die Quelle.

    Die zweite sieht das gebaute Binary an und steht in `build.sh` — ein
    Versprechen, das nur im Quelltext steht, ist keines.
    """
    code = _swift_ohne_prosa(SIDECAR_SWIFT.read_text())
    for verboten in ("save(", "remove(", ".commit(", "saveEvent", "removeEvent",
                     "saveCalendar", "removeCalendar"):
        assert verboten not in code, f"Schreibaufruf im Sidecar: {verboten}"


def test_der_build_prueft_die_schreibfreiheit_am_binary():
    text = BUILD_SH.read_text()
    assert "Schreibselektor" in text
    assert "exit 3" in text, "Der Build muss bei einem Fund abbrechen"


def test_das_modul_kennt_keine_mutierende_operation():
    from personaljarvis.calendar.bridge import protocol

    assert protocol.MUTATING_OPERATIONS == frozenset()
    assert not (protocol.READ_OPERATIONS & protocol.MUTATING_OPERATIONS)


def test_die_api_bietet_keinen_schreibenden_endpunkt():
    from fastapi import FastAPI

    from personaljarvis.calendar.api import create_calendar_router
    from personaljarvis.calendar.lifecycle import CalendarModule

    class _Factory:
        pass

    router = create_calendar_router(
        CalendarModule(_Factory(), workspace_id="w", provider_account_id="p"))
    app = FastAPI()
    app.include_router(router)
    pfade = {(r.path, tuple(sorted(r.methods))) for r in app.routes
             if hasattr(r, "methods")}
    schreibend = {p for p, m in pfade
                  if any(x in m for x in ("PUT", "PATCH", "DELETE"))}
    assert not schreibend, schreibend
    # Die drei POST-Routen sind Handlungen, aber keine Provider-Mutationen.
    posts = {p for p, m in pfade if "POST" in m}
    assert posts == {"/v1/personal/calendar/bridge/check",
                     "/v1/personal/calendar/authorization",
                     "/v1/personal/calendar/sync"}


# ── Berechtigung nur auf Nutzeraktion ────────────────────────────────────────
def test_der_client_verweigert_eine_anfrage_ohne_nutzeraktion():
    from personaljarvis.base.sidecar.errors import BridgeProtocolError
    from personaljarvis.calendar.bridge.client import CalendarBridgeClient

    client = CalendarBridgeClient.__new__(CalendarBridgeClient)
    with pytest.raises(BridgeProtocolError):
        CalendarBridgeClient.request_authorization(client, user_initiated=False)


def test_der_sidecar_fragt_nur_mit_ausdruecklichem_payload():
    code = SIDECAR_SWIFT.read_text()
    assert 'payload["request"] as? Bool) == true' in code


def test_write_only_gilt_nie_als_leseberechtigung():
    from personaljarvis.calendar.bridge.models import AuthorizationStatus

    assert AuthorizationStatus.WRITE_ONLY.can_read is False
    assert AuthorizationStatus.FULL_ACCESS.can_read is True
    assert AuthorizationStatus.UNKNOWN.can_read is False


def test_ein_unbekannter_status_wird_nie_geraten():
    from personaljarvis.calendar.bridge.models import AuthorizationStatus

    assert AuthorizationStatus.parse("etwas_neues") is AuthorizationStatus.UNKNOWN


def test_der_status_kommt_aus_dem_rohwert_nicht_aus_dem_enum_fall():
    """Genau hier scheiterte der alte Jarvis-Kalender auf macOS 14.

    Sein `@unknown default` meldete jeden neuen Wert als `unknown`, worauf das
    authorized-Gate trotz erteiltem Vollzugriff schloss. Der Rohwertweg
    kompiliert auf beiden SDK-Staenden und kennt `writeOnly` (4).
    """
    code = SIDECAR_SWIFT.read_text()
    assert "authorizationStatus(for: .event).rawValue" in code
    assert "case 4:  return \"write_only\"" in code
    # Die macOS-14-Symbole duerfen im echten CODE nicht vorkommen — das
    # 13.1-SDK kennt sie nicht. Im erlaeuternden Kommentar stehen sie sehr
    # wohl, und genau deshalb wird hier ohne Prosa geprueft.
    ohne_prosa = _swift_ohne_prosa(code)
    assert ".fullAccess" not in ohne_prosa
    assert ".writeOnly" not in ohne_prosa


def test_die_macos14_api_wird_zur_laufzeit_gesucht():
    code = SIDECAR_SWIFT.read_text()
    assert "requestFullAccessToEventsWithCompletion:" in code
    assert "responds(to: modern)" in code


# ── Keine zweite Infrastruktur ───────────────────────────────────────────────
def test_der_kalender_baut_keine_eigene_prozessfuehrung():
    """Prozessführung, Auflösung und Fehlerklassen sind gemeinsam."""
    for datei in CALENDAR_SRC.rglob("*.py"):
        code = _python_code_ohne_prosa(datei)
        for begriff in ("subprocess", "Popen", "os.system", "os.exec"):
            assert begriff not in code, f"{datei.name}: {begriff}"


def test_der_kalender_nutzt_die_gemeinsamen_primitive():
    from personaljarvis.base.sidecar.process import SidecarProcess
    from personaljarvis.calendar.bridge.process import CalendarSidecarProcess
    from personaljarvis.contacts.bridge.process import (
        SidecarProcess as ContactsProcess,
    )

    assert issubclass(CalendarSidecarProcess, SidecarProcess)
    assert issubclass(ContactsProcess, SidecarProcess)


def test_kontakte_und_kalender_teilen_die_fehlerklassen():
    """Ein `except BridgeError` faengt hier wie dort dasselbe Objekt."""
    from personaljarvis.base.sidecar.errors import BridgeError
    from personaljarvis.calendar.bridge import BridgeError as CalError
    from personaljarvis.contacts.bridge.errors import BridgeError as ConError

    assert CalError is BridgeError
    assert ConError is BridgeError


def test_der_kalender_haengt_nicht_am_kontaktmodul():
    """Modulgrenze: Kalender importiert keinen Kontakte-Code."""
    for datei in CALENDAR_SRC.rglob("*.py"):
        text = datei.read_text()
        assert "personaljarvis.contacts" not in text, datei.name


def test_der_kalender_importiert_keine_spikes():
    for datei in CALENDAR_SRC.rglob("*.py"):
        text = datei.read_text()
        for muster in ("import spikes", "from spikes", '"spikes/', "'spikes/",
                       "calendar-foundation"):
            assert muster not in text, f"{datei.name}: {muster}"


def test_der_kalender_teilt_die_datenbankverbindung_des_bootstraps():
    """Zwei Factories auf derselben Datei waeren zwei Schreiber (07 §5)."""
    quelle = (REPO_ROOT / "src/personaljarvis/calendar/lifecycle.py").read_text()
    assert "ConnectionFactory(" not in _python_code_ohne_prosa(
        REPO_ROOT / "src/personaljarvis/calendar/lifecycle.py")
    assert "factory: ConnectionFactory" in quelle


# ── Berechtigung und Packaging ───────────────────────────────────────────────
def test_die_app_traegt_das_kalender_entitlement():
    """Ohne dieses Entitlement fragt tccd unter Hardened Runtime gar nicht."""
    text = (TAURI / "Entitlements.plist").read_text()
    assert "com.apple.security.personal-information.calendars" in text
    # Das Kontakt-Pendant bleibt unberuehrt.
    assert "com.apple.security.personal-information.addressbook" in text


def test_der_sidecar_traegt_genau_ein_entitlement():
    text = (TAURI / "CalendarSidecar.entitlements").read_text()
    assert "com.apple.security.personal-information.calendars" in text
    for verboten in ("allow-jit", "network.client", "network.server",
                     "disable-library-validation", "files.user-selected",
                     "com.apple.security.inherit"):
        # Der Begriff darf im erlaeuternden Kommentar stehen, aber nie als
        # <key> — deshalb wird auf die Schluesselform geprueft.
        assert f"<key>com.apple.security.{verboten}" not in text


def test_beide_usage_description_schluessel_sind_eingebettet():
    """`NSCalendarsUsageDescription` gilt bis macOS 13, `…FullAccess…` ab 14."""
    text = BUILD_SH.read_text()
    assert "NSCalendarsUsageDescription" in text
    assert "NSCalendarsFullAccessUsageDescription" in text


def test_der_sidecar_ist_als_external_bin_registriert():
    conf = json.loads((TAURI / "tauri.conf.json").read_text())
    binaries = conf["bundle"]["externalBin"]
    assert "binaries/jarvis-calendar" in binaries


def test_das_reseal_deckt_beide_sidecars_ab():
    text = (TAURI / "scripts/reseal-contacts-sidecar.sh").read_text()
    assert "jarvis-calendar" in text
    assert "jarvis-contacts" in text
    assert "CalendarSidecar.entitlements" in text


def test_der_build_haelt_die_mindestversion_ein():
    assert 'MIN_MACOS="${MIN_MACOS:-12.3}"' in BUILD_SH.read_text()


# ── Datenminimierung in Diagnosen ────────────────────────────────────────────
def test_die_bridge_diagnose_traegt_keinen_termininhalt():
    """stderr ist Diagnose, nie Inhalt."""
    code = SIDECAR_SWIFT.read_text()
    # Jede diag()-Zeile wird geprueft: keine Interpolation eines Termin- oder
    # Kalenderwerts.
    for zeile in code.splitlines():
        if "diag(" not in zeile:
            continue
        for verboten in ("e.title", "e.notes", "e.location", "c.title",
                         "eventIdentifier", "calendarIdentifier"):
            assert verboten not in zeile, zeile.strip()

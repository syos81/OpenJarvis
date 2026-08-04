"""Prüft die Berichte der Kalender-Leseprobe — ohne EventKit, ohne Gerät.

Der Spike hat zwei Zusagen gemacht, und beide sind hier nachprüfbar statt nur
behauptet: **er schreibt nicht**, und **er gibt keine Inhalte heraus**. Das
zweite ist der Grund, warum die Berichte überhaupt im Repository liegen dürfen.

Die Golden-Dateien stammen aus dem Livelauf vom 2026-08-04 auf x86_64.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HIER = Path(__file__).parent
FIXTURES = HIER / "fixtures"
PROBE = FIXTURES / "probe-x86_64-2026-08-04.json"
SPAWN = FIXTURES / "spawn-x86_64-2026-08-04.json"

#: `K-` Kalender, `S-` Quelle — dieselbe Bildung wie `C-…` im Kontaktmodul.
MASKE = re.compile(r"^[KS]-[0-9a-f]{12}$")

#: Alles, was nach einer rohen Apple-Kennung aussieht. EventKit gibt
#: Kalender-IDs als UUID heraus und Ereignis-IDs als UUID mit Zusatz.
ROHKENNUNG = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
                        r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


@pytest.fixture(scope="module")
def probe() -> dict:
    return json.loads(PROBE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def spawn() -> dict:
    return json.loads(SPAWN.read_text(encoding="utf-8"))


# ── Die read-only-Grenze ─────────────────────────────────────────────────────

def test_bericht_erklaert_ausdruecklich_keinen_schreibversuch(probe):
    assert probe["write_attempted"] is False


def test_die_quelle_enthaelt_keine_schreib_api():
    """Der wirksamste Test der Auftragsgrenze ist der billigste.

    Wer hier eine Mutation ergänzt, lässt diesen Test fallen — und zwar bevor
    irgendein Gerät beteiligt ist. Kommentare werden vorher entfernt: die
    Datei *beschreibt* die verbotenen Aufrufe, und das soll sie dürfen.
    """
    roh = (HIER / "src" / "main.swift").read_text(encoding="utf-8")
    code = "\n".join(z.split("//", 1)[0] for z in roh.splitlines())
    for verboten in ("EKEvent(", ".save(", ".remove(", "saveEvent",
                     "removeEvent", "commit("):
        assert verboten not in code, f"Schreib-API im Spike: {verboten}"


# ── Die PII-Grenze ───────────────────────────────────────────────────────────

def test_keine_rohkennung_in_den_berichten():
    for datei in (PROBE, SPAWN):
        text = datei.read_text(encoding="utf-8")
        assert not ROHKENNUNG.search(text), f"rohe Kennung in {datei.name}"


def test_alle_verweise_sind_maskiert(probe):
    for zeile in probe["calendars"]["rows"]:
        assert MASKE.match(zeile["calendar_ref"])
        assert MASKE.match(zeile["source_ref"])
    for ref in probe["events"]["per_calendar"]:
        assert MASKE.match(ref)
    assert MASKE.match(probe["calendars"]["default_for_new_events"])


def _alle_schluessel(objekt) -> set[str]:
    if isinstance(objekt, dict):
        gefunden = set(objekt)
        for wert in objekt.values():
            gefunden |= _alle_schluessel(wert)
        return gefunden
    if isinstance(objekt, list):
        gefunden: set[str] = set()
        for eintrag in objekt:
            gefunden |= _alle_schluessel(eintrag)
        return gefunden
    return set()


def test_keine_inhaltsfelder_im_bericht(probe):
    """Titel, Ort, Notiz, Teilnehmerin — nichts davon darf ein Schlüssel sein.

    Geprüft wird über die Schlüsselmenge, nicht über den Rohtext: `with_location`
    ist eine Zählung und muss erlaubt bleiben, `location` wäre ein Inhalt.
    """
    verboten = {"title", "location", "notes", "url", "attendees", "organizer",
                "email", "start_date", "end_date", "participants", "identifier"}
    assert verboten & _alle_schluessel(probe) == set()


# ── Der Befund selbst ────────────────────────────────────────────────────────

def test_lesen_war_erfolgreich(probe):
    assert probe["ok"] is True
    assert probe["authorization_status"] == "authorized"


def test_kalenderzahlen_sind_in_sich_stimmig(probe):
    k = probe["calendars"]
    assert k["count"] == len(k["rows"])
    assert sum(k["by_type"].values()) == k["count"]
    assert sum(k["by_source_type"].values()) == k["count"]
    assert k["writable"] == sum(1 for z in k["rows"] if z["allows_modifications"])
    # Genau die Kalender, die der Spike nicht ändern darf und nie ändern wird.
    assert k["immutable"] >= 1
    assert k["subscribed"] >= 1


def test_terminzahlen_sind_in_sich_stimmig(probe):
    e = probe["events"]
    assert sum(e["per_calendar"].values()) == e["count"]
    for merkmal in ("all_day", "recurring", "with_attendees", "with_alarms",
                    "detached_occurrences", "cancelled"):
        assert 0 <= e[merkmal] <= e["count"]


def test_jeder_termin_trug_beide_kennungen(probe):
    """Grundlage des External-ID-Modells.

    Fehlt eine Kennung oder teilen sich zwei Datensätze eine, taugt sie nicht
    als Schlüssel. Im Fenster vom 2026-08-04 war beides nicht der Fall — das
    ist ein Befund über *dieses* Fenster, keine Zusage über alle Bestände.
    """
    e = probe["events"]
    assert e["missing_event_identifier"] == 0
    assert e["missing_external_identifier"] == 0
    assert e["event_identifier_collisions"] == 0
    assert e["external_identifier_collisions"] == 0


def test_das_fenster_ist_benannt(probe):
    """EventKit kennt kein „alle Termine". Jeder Lesebericht nennt sein Fenster."""
    f = probe["window"]
    assert f["days_back"] > 0 and f["days_forward"] > 0
    assert f["start"] < f["end"]


# ── Die Architekturfrage ─────────────────────────────────────────────────────

def test_das_nicht_gebuendelte_kind_erbte_den_zugriff(spawn):
    """Der Befund, der den Prozessort entscheidet.

    Das Kind ist ein nacktes CLI-Binary ohne eigenes Bündel und ohne eigenes
    Entitlement. Es liest trotzdem — TCC urteilt über den *verantwortlichen*
    Prozess, nicht über die Kennung des Kindes. Ein Sidecar ist damit möglich.
    """
    assert spawn["parent_authorization_status"] == "authorized"
    assert spawn["child_binary_is_bundled"] is False
    assert spawn["child_launch_error"] == ""
    assert spawn["child_exit_code"] == 0
    assert spawn["child"]["ok"] is True
    assert spawn["child"]["authorization_status"] == "authorized"
    assert spawn["child"]["calendar_count"] == spawn["child"]["calendar_count"]


def test_kind_und_elternteil_sahen_denselben_bestand(probe, spawn):
    assert spawn["child"]["calendar_count"] == probe["calendars"]["count"]

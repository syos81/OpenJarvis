"""Diagnose eines nativen Sidecar-Absturzes. **Kontaktfrei.**

Kein `CNContactStore`, kein echter Sidecar, kein Prozess gegen Apple Contacts:
geprüft wird ausschliesslich die Filterfunktion und — über ein winziges
Shell-Skript, das nur nach stderr schreibt und sich beendet — der Weg vom
Kindprozess bis in die Diagnose.

**Anlass.** Beim Create-Livetest am 2026-08-01 starb der Sidecar an einer nicht
abgefangenen Objective-C-Ausnahme mitten in Apples Save-Pfad. Die alte
Allowlist liess ausschliesslich eigene `[contacts-bridge]`-Zeilen durch; der
gesamte Ausnahmedump wurde durch identische Platzhalter ersetzt. Die Ursache
war nur noch aus dem Absturzbericht des Systems zu rekonstruieren — genau der
Diagnoseverlust, der schon im arm64-SIGABRT-Bericht vom 2026-07-28 benannt
worden war.

Die Tests halten beide Seiten fest: **was erhalten bleiben muss** (die
Ausnahmeklasse, der Laufzeitmarker, Rahmen aus Apple-Bibliotheken) und **was
niemals durchkommen darf** (Kontaktwerte, Pfade, Kennungen, der Freitext des
`reason`).
"""

from __future__ import annotations

import pytest

from personaljarvis.contacts.bridge.process import (
    _STDERR_MAX_LEN,
    SidecarProcess,
    _technische_stderr_zeile,
)
from personaljarvis.contacts.bridge.resolver import SidecarLocation

# Eine realistische Absturzausgabe. Der `reason` trägt hier absichtlich einen
# erfundenen Kontaktwert — genau das, was nicht durchkommen darf.
DUMP = [
    "*** Terminating app due to uncaught exception 'NSInvalidArgumentException', "
    "reason: 'Kontakt ZZZ-Geheimname konnte nicht gesichert werden'",
    "*** First throw call stack:",
    "0   CoreFoundation    0x00007ff80876d6e3 __exceptionPreprocess + 242",
    "1   libobjc.A.dylib   0x00007ff8084cd8bb objc_exception_throw + 48",
    "6   CoreData          0x00007ff80e66c0d7 -[NSManagedObjectContext save:] + 1959",
    "8   Contacts          0x00007ff81a4cbfaa "
    "-[CNCDSaveRequestExecutor executeSaveRequest:] + 612",
    "libc++abi: terminating with uncaught exception of type NSException",
]


# ═══ Was erhalten bleiben muss ══════════════════════════════════════════════
def test_die_ausnahmeklasse_ueberlebt():
    """Ohne sie bliebe von einem SIGABRT nur „irgendetwas ging schief"."""
    zeile = _technische_stderr_zeile(DUMP[0])
    assert zeile is not None
    assert "NSInvalidArgumentException" in zeile


def test_der_laufzeitmarker_ueberlebt():
    zeile = _technische_stderr_zeile(DUMP[-1])
    assert zeile is not None
    assert "NSException" in zeile


def test_apple_rahmen_ueberleben_mit_symbol():
    zeile = _technische_stderr_zeile(DUMP[5])
    assert zeile is not None
    assert "Contacts" in zeile
    assert "executeSaveRequest" in zeile


def test_der_gesamte_dump_bleibt_auswertbar():
    """Aus der gefilterten Fassung muss die Ursache noch ablesbar sein."""
    gefiltert = [_technische_stderr_zeile(z) for z in DUMP]
    text = " ".join(z for z in gefiltert if z)
    assert "NSInvalidArgumentException" in text
    assert "NSManagedObjectContext save" in text
    assert "CNCDSaveRequestExecutor" in text


# ═══ Was niemals durchkommen darf ═══════════════════════════════════════════
def test_der_freitext_des_reason_wird_nicht_uebernommen():
    """`reason` ist Freitext, den Apple mit beliebigen Werten füllen darf."""
    zeile = _technische_stderr_zeile(DUMP[0])
    assert "ZZZ-Geheimname" not in zeile
    assert "gesichert" not in zeile
    # Dass es einen gab, darf stehen — was drinstand, nicht.
    assert "reason vorhanden" in zeile


@pytest.mark.parametrize("zeile", [
    "Kontakt: Max Mustermann, max@privat.example",
    "  Pfad /Users/jemand/Library/Application Support/AddressBook kaputt",
    "container 01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount nicht lesbar",
    "cursor AAAAB3NzaC1yc2EAAAADAQABAAABgQ=",
])
def test_nicht_technische_zeilen_werden_verworfen(zeile):
    assert _technische_stderr_zeile(zeile) is None


def test_ein_pfad_kann_nicht_als_symbol_durchrutschen():
    """Die Symbol-Zeichenklasse lässt bewusst kein `/` zu."""
    getarnt = "3   Foo   0x00007ff800000000 /Users/jemand/geheim/pfad"
    zeile = _technische_stderr_zeile(getarnt)
    assert zeile is None or "/Users" not in zeile


def test_keine_zeile_wird_woertlich_uebernommen():
    """Jede Ausgabe ist zusammengesetzt, keine ist ein Durchreichen."""
    for roh in DUMP:
        zeile = _technische_stderr_zeile(roh)
        if zeile is not None:
            assert zeile.startswith("[nativ] ")
            assert zeile != roh


# ═══ Der Weg durch den Prozess ══════════════════════════════════════════════
def _prozess_mit_stderr(tmp_path, zeilen: list[str]) -> SidecarProcess:
    """Ein Skript, das ausschliesslich nach stderr schreibt und endet.

    Es spricht kein Protokoll und berührt keinen Store — es dient nur dazu,
    den Weg von stderr bis in `safe_stderr()` zu belegen.
    """
    from personaljarvis.contacts.bridge.resolver import host_architecture

    pfad = tmp_path / "attrappe"
    ausgabe = "\n".join(f"echo {zeile!r} >&2" for zeile in zeilen)
    pfad.write_text(f"#!/bin/sh\n{ausgabe}\nexit 1\n")
    pfad.chmod(0o755)
    arch = host_architecture()
    return SidecarProcess(SidecarLocation(
        path=pfad, architectures=(arch,), host_architecture=arch))


def test_stderr_erreicht_die_diagnose_gefiltert(tmp_path):
    from personaljarvis.contacts.bridge.errors import BridgeError

    prozess = _prozess_mit_stderr(tmp_path, DUMP)
    with pytest.raises(BridgeError):
        prozess.start(timeout=5.0)          # kein Handshake — erwartet
    prozess.stop()

    tail = " ".join(prozess.safe_stderr())
    assert "NSInvalidArgumentException" in tail
    assert "ZZZ-Geheimname" not in tail
    assert "/Users" not in tail


def test_eigene_diagnosezeilen_bleiben_unveraendert(tmp_path):
    from personaljarvis.contacts.bridge.errors import BridgeError

    eigen = "[contacts-bridge] create not_sent: invalid_request"
    prozess = _prozess_mit_stderr(tmp_path, [eigen])
    with pytest.raises(BridgeError):
        prozess.start(timeout=5.0)
    prozess.stop()
    assert eigen in prozess.safe_stderr()


def test_die_laenge_bleibt_begrenzt(tmp_path):
    lang = ("2   CoreData   0x00007ff800000000 -[Sehr" + "Lang" * 200
            + " methode:]")
    zeile = _technische_stderr_zeile(lang)
    assert zeile is None or len(zeile) <= _STDERR_MAX_LEN


# ═══ Die Klassifikation bleibt unberührt ════════════════════════════════════
def test_die_diagnose_aendert_keine_ergebnisklassifikation():
    """Diese Korrektur berührt Send-, Retry- und Ausgangsentscheidung nicht."""
    import inspect

    from personaljarvis.contacts.bridge import process as P

    quelle = inspect.getsource(P._technische_stderr_zeile)
    for verboten in ("MutationOutcome", "outcome", "not_sent", "retry",
                     "failure_class"):
        assert verboten not in quelle, verboten
    # Die Zuordnung Abbruchklasse → `mutation_outcome_unknown` steht
    # unveraendert an ihrer Stelle.
    assert "MutationOutcomeUnknown" in inspect.getsource(P.SidecarProcess._fail)

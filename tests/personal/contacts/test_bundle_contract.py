"""Der Bundlevertrag — Positivnachweis und vier Negativproben.

**Kontaktfrei.** Geprüft werden ausschliesslich gebaute Artefakte. Kein
Store-Zugriff, kein TCC-Dialog, kein Start des Helfers.

**Das Original wird nie angefasst.** Jede Negativprobe arbeitet auf einer
Kopie in `tmp_path`, die dort neu signiert wird. Das gepackte Bundle bleibt
byteweise unverändert; der Positivtest läuft deshalb auch nach den
Negativproben noch grün.

Warum es Negativproben braucht: Ein Torwächter, der nur bei korrekten
Artefakten grün meldet, ist von einem Torwächter, der immer grün meldet, nicht
zu unterscheiden. Geprüft wird deshalb je einzeln, dass er **erkennt**:
Adhoc-Signatur, falscher Identifier, falsches Entitlement-Set, falsches
Zertifikatsblatt.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from personaljarvis.contacts.bridge.resolver import tauri_triple  # noqa: E402
from tools.packaging import bundle_contract as bc  # noqa: E402

_REPO = Path(__file__).resolve().parents[3]
_SRC_TAURI = _REPO / "frontend/src-tauri"
_BUNDLE = (_SRC_TAURI / "target" / tauri_triple()
           / "release/bundle/macos/Jarvis.app")
_HELPER = _BUNDLE / "Contents/MacOS/contacts-write-helper"

#: Der Spec des Schreibhelfers — dieselbe Quelle, die auch der Build benutzt.
_SPEC = next(s for s in bc.BUNDLE_SPECS if s.name == "contacts-write-helper")

_PRODUKTIV = "de.kluender.jarvis"
#: Eine **andere** Identität desselben Schlüsselbunds. Sie ist der einzige
#: ehrliche Weg, „falsches Blatt" zu prüfen: ein erfundener Fingerabdruck
#: prüfte nur die Zeichenkette, nicht die Signatur.
_FREMD = "Personal Jarvis Contacts Spike"


def _identitaeten() -> set[str]:
    proc = subprocess.run(["security", "find-identity", "-v", "-p",
                           "codesigning"], capture_output=True, text=True)
    return {zeile.split('"')[1] for zeile in proc.stdout.splitlines()
            if '"' in zeile}


_VERFUEGBAR = _identitaeten()

pytestmark = [
    pytest.mark.skipif(not _HELPER.is_file(),
                       reason="Bundle nicht gebaut "
                              "(frontend/src-tauri/scripts/build-product.sh)"),
    pytest.mark.skipif(_PRODUKTIV not in _VERFUEGBAR,
                       reason=f"Signaturidentität {_PRODUKTIV} fehlt"),
]


def _leaf() -> str:
    return bc.leaf_of(bc.designated_requirement(_HELPER))


def _kopie(tmp_path: Path) -> Path:
    ziel = tmp_path / "contacts-write-helper"
    shutil.copy2(_HELPER, ziel)
    return ziel


def _signiere(pfad: Path, *, identity: str, identifier: str,
              entitlements: Path | None) -> None:
    args = ["/usr/bin/codesign", "--force", "--sign", identity,
            "--identifier", identifier, "--options", "runtime",
            "--timestamp=none"]
    if entitlements is not None:
        args += ["--entitlements", str(entitlements)]
    args.append(str(pfad))
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr


def _verletzungen(pfad: Path, **kwargs) -> dict[str, bc.Finding]:
    befunde = bc.verify_binary(pfad, _SPEC, entitlements_dir=_SRC_TAURI,
                               **kwargs)
    return {b.check: b for b in befunde if not b.ok}


# ═══ Positiv ════════════════════════════════════════════════════════════════
def test_das_gepackte_bundle_erfuellt_den_vertrag():
    befunde = bc.verify_app(_BUNDLE, entitlements_dir=_SRC_TAURI,
                            expected_leaf=_leaf(),
                            expected_triple=tauri_triple())
    verletzt = [str(b) for b in befunde if not b.ok]
    assert not verletzt, "\n".join(verletzt)
    assert len(befunde) >= 30, "Ein fast leerer Pflichtscan ist kein Nachweis"


def test_der_pflichtscan_ist_nicht_leer():
    """Dauerregeln §9: Eine leere Aggregation besteht nie.

    Der Scan muss jedes der vier Mach-O tatsächlich erreicht haben — sonst
    meldet er grün über etwas, das er nie gelesen hat.
    """
    befunde = bc.verify_app(_BUNDLE, entitlements_dir=_SRC_TAURI,
                            expected_triple=tauri_triple())
    geprueft = {b.binary for b in befunde}
    assert {s.name for s in bc.BUNDLE_SPECS} <= geprueft


# ═══ Negativ — je eine Abweichung auf einer Kopie ═══════════════════════════
def test_adhoc_signatur_wird_erkannt(tmp_path):
    kopie = _kopie(tmp_path)
    subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-",
                    "--options", "runtime", str(kopie)],
                   check=True, capture_output=True)
    schlecht = _verletzungen(kopie)
    assert "signatur" in schlecht
    assert schlecht["signatur"].actual == "adhoc"
    # Adhoc bindet an den Codehash statt an ein Zertifikat — auch die
    # Designated Requirement muss das zeigen.
    assert "dr-zertifikatsgebunden" in schlecht


def test_falscher_identifier_wird_erkannt(tmp_path):
    kopie = _kopie(tmp_path)
    _signiere(kopie, identity=_PRODUKTIV,
              identifier="de.kluender.jarvis.nicht-der-helfer",
              entitlements=_SRC_TAURI / "ContactsWriteHelper.entitlements")
    schlecht = _verletzungen(kopie)
    assert "identifier" in schlecht
    assert schlecht["identifier"].actual == "de.kluender.jarvis.nicht-der-helfer"
    assert "dr-identifier" in schlecht


def test_falsches_entitlement_set_wird_erkannt(tmp_path):
    """Der Fehler des unbehandelten `tauri build`: die Rechte der Anwendung."""
    kopie = _kopie(tmp_path)
    _signiere(kopie, identity=_PRODUKTIV, identifier=_SPEC.identifier,
              entitlements=_SRC_TAURI / "Entitlements.plist")
    schlecht = _verletzungen(kopie)
    assert "entitlements" in schlecht
    gemessen = schlecht["entitlements"].actual
    assert "com.apple.security.cs.allow-jit" in gemessen
    assert "com.apple.security.network.client" in gemessen
    # Identifier und Blatt stimmen dabei — genau deshalb reicht eine
    # Sammelprüfung nicht.
    assert "identifier" not in schlecht


def test_leeres_entitlement_set_wird_erkannt(tmp_path):
    """Gar kein Recht ist genauso falsch wie zu viele — nur unauffälliger."""
    kopie = _kopie(tmp_path)
    _signiere(kopie, identity=_PRODUKTIV, identifier=_SPEC.identifier,
              entitlements=None)
    schlecht = _verletzungen(kopie)
    assert "entitlements" in schlecht
    assert schlecht["entitlements"].actual == "(leer)"


@pytest.mark.skipif(_FREMD not in _VERFUEGBAR,
                    reason=f"Vergleichsidentität {_FREMD} fehlt")
def test_falsches_blatt_wird_erkannt(tmp_path):
    kopie = _kopie(tmp_path)
    _signiere(kopie, identity=_FREMD, identifier=_SPEC.identifier,
              entitlements=_SRC_TAURI / "ContactsWriteHelper.entitlements")
    schlecht = _verletzungen(kopie, expected_leaf=_leaf())
    assert "blatt" in schlecht
    assert schlecht["blatt"].actual != _leaf()
    # Alles andere ist in Ordnung: Identifier, Rechte, Hardened Runtime. Ein
    # `codesign --verify --deep --strict` bliebe hier gruen.
    assert set(schlecht) == {"blatt"}


def test_fehlendes_binary_wird_erkannt(tmp_path):
    schlecht = _verletzungen(tmp_path / "gibt-es-nicht")
    assert "vorhanden" in schlecht


# ═══ Das Original hat die Negativproben unbeschadet ueberstanden ════════════
def test_das_original_ist_nach_den_negativproben_unveraendert():
    befunde = bc.verify_binary(_HELPER, _SPEC, entitlements_dir=_SRC_TAURI,
                               expected_leaf=_leaf())
    assert not [str(b) for b in befunde if not b.ok]

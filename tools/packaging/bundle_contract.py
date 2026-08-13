"""Der Signatur- und Entitlementvertrag des gepackten Bundles.

**Warum es diese Datei gibt.** `tauri build` signiert jedes Mach-O im Bundle
mit den Entitlements der *Anwendung*. Für das Hauptbinary ist das richtig, für
den Schreibhelfer und die beiden Sidecars nicht: Sie erben damit JIT,
unsignierten ausführbaren Speicher, abgeschaltete Library-Validation, beide
Netzrechte und den Kalenderzugriff — und, weil `signingIdentity` in
`tauri.conf.json` auf `-` steht, eine Adhoc-Signatur mit generiertem
Identifier. `reseal-contacts-sidecar.sh` stellt den gültigen Zustand her.

Bis 2026-08-13 hing das daran, dass jemand den Nachschritt kennt. Schlimmer:
`tauri build` erzeugt das DMG **vor** dem Reseal, sodass selbst ein
durchgeführter Reseal nur den Targetordner reparierte und das ausgelieferte
Image den vertragswidrigen Helfer behielt. Gemessen am Integrationsstand:
`Signature=adhoc`, Identifier `contacts-write-helper-5555…`, neun Entitlements
— im fertigen `Jarvis_1.0.1_aarch64.dmg`.

Dieses Modul ist die **eine** Stelle, an der steht, was am Ende gelten muss.
Es liest sie nicht aus sich selbst, sondern aus den bereits vorhandenen
`.entitlements`-Dateien: Wer den Vertrag ändert, ändert die Datei, die auch
signiert wird — nicht zwei Wahrheiten, die auseinanderlaufen können.

Zwei Leser benutzen es:

* `scripts/build-product.sh` als Torwächter des kanonischen Produktbuilds,
* `tests/personal/contacts/test_bundle_contract.py` mit Positiv- und
  Negativproben auf **Kopien**, nie auf dem produktiven Original.

`codesign --deep` allein zählt hier ausdrücklich nicht als Nachweis: Es prüft
die Gültigkeit der Siegelung, nicht *wessen* Siegel, unter welchem Identifier
und mit welchen Rechten. Identifier, Entitlements, Blatt und Architektur
werden deshalb einzeln erhoben.
"""

from __future__ import annotations

import argparse
import plistlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BinarySpec",
    "Finding",
    "BUNDLE_SPECS",
    "APP_IDENTIFIER",
    "entitlement_keys",
    "signature_facts",
    "designated_requirement",
    "leaf_of",
    "architectures",
    "verify_binary",
    "verify_app",
    "format_findings",
]

APP_IDENTIFIER = "de.kluender.jarvis"

#: Ein Mach-O des Bundles und was für es gilt.
#:
#: `entitlements_file` verweist relativ auf `frontend/src-tauri/`. Die erwartete
#: Rechtemenge ist der Schlüsselvorrat genau dieser Datei — die Menge steht
#: nicht ein zweites Mal hier im Code.


@dataclass(frozen=True)
class BinarySpec:
    name: str
    identifier: str
    entitlements_file: str


BUNDLE_SPECS: tuple[BinarySpec, ...] = (
    BinarySpec("openjarvis-desktop", APP_IDENTIFIER, "Entitlements.plist"),
    BinarySpec("contacts-write-helper", f"{APP_IDENTIFIER}.contacts-write-helper",
               "ContactsWriteHelper.entitlements"),
    BinarySpec("jarvis-contacts", f"{APP_IDENTIFIER}.contacts-bridge",
               "ContactsSidecar.entitlements"),
    BinarySpec("jarvis-calendar", f"{APP_IDENTIFIER}.calendar-bridge",
               "CalendarSidecar.entitlements"),
)

#: Rust-Triple → Architektur, wie `lipo -info` sie nennt.
_TRIPLE_ARCH = {
    "aarch64-apple-darwin": "arm64",
    "x86_64-apple-darwin": "x86_64",
}

_LEAF = re.compile(r'certificate leaf\s*=\s*H"([0-9a-fA-F]+)"')


@dataclass(frozen=True)
class Finding:
    """Ein einzelnes Prüfergebnis. `ok=False` ist ein Vertragsbruch."""

    binary: str
    check: str
    expected: str
    actual: str
    ok: bool

    def __str__(self) -> str:
        marke = "OK  " if self.ok else "FAIL"
        return (f"{marke} {self.binary}/{self.check}: "
                f"erwartet {self.expected!r}, gemessen {self.actual!r}")


def _run(*args: str) -> tuple[int, str]:
    """codesign schreibt seine Auskünfte nach stderr — beides wird gelesen."""
    proc = subprocess.run(args, capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def entitlement_keys(pfad: Path) -> frozenset[str]:
    """Der tatsächliche Rechtevorrat eines Binaries — leer heisst leer."""
    proc = subprocess.run(
        ["/usr/bin/codesign", "-d", "--entitlements", "-", "--xml", str(pfad)],
        capture_output=True, timeout=120)
    roh = proc.stdout or b""
    anfang = roh.find(b"<?xml")
    if anfang < 0:
        return frozenset()
    try:
        geladen = plistlib.loads(roh[anfang:])
    except Exception:
        return frozenset()
    if not isinstance(geladen, dict):
        return frozenset()
    return frozenset(geladen)


def expected_entitlement_keys(entitlements_datei: Path) -> frozenset[str]:
    """Der Sollvorrat — aus derselben Datei, die auch signiert wird."""
    with entitlements_datei.open("rb") as fh:
        geladen = plistlib.load(fh)
    return frozenset(geladen) if isinstance(geladen, dict) else frozenset()


def signature_facts(pfad: Path) -> dict[str, str]:
    """Identifier, Signaturart, Autorität und CodeDirectory-Flags.

    `codesign -dv` nennt `Signature=adhoc` **nur** im Adhoc-Fall; ein mit einem
    Zertifikat gesiegeltes Binary schweigt dazu und weist sich stattdessen über
    `Authority=` aus. Die Abwesenheit einer Zeile ist deshalb kein Befund —
    gefragt wird nach beidem.
    """
    _, ausgabe = _run("/usr/bin/codesign", "-dvvv", str(pfad))
    fakten: dict[str, str] = {"identifier": "", "signature": "",
                              "authority": "", "flags": ""}
    for zeile in ausgabe.splitlines():
        if zeile.startswith("Identifier="):
            fakten["identifier"] = zeile.split("=", 1)[1].strip()
        elif zeile.startswith("Signature="):
            fakten["signature"] = zeile.split("=", 1)[1].strip()
        elif zeile.startswith("Authority=") and not fakten["authority"]:
            fakten["authority"] = zeile.split("=", 1)[1].strip()
        elif "flags=" in zeile:
            treffer = re.search(r"flags=\S+\(([^)]*)\)", zeile)
            fakten["flags"] = treffer.group(1) if treffer else ""
    return fakten


def designated_requirement(pfad: Path) -> str:
    _, ausgabe = _run("/usr/bin/codesign", "-d", "-r-", str(pfad))
    for zeile in ausgabe.splitlines():
        if zeile.startswith("designated =>"):
            return zeile.split("=>", 1)[1].strip()
    return ""


def leaf_of(dr: str) -> str:
    """Das Zertifikatsblatt der Designated Requirement, klein geschrieben."""
    treffer = _LEAF.search(dr)
    return treffer.group(1).lower() if treffer else ""


def architectures(pfad: Path) -> tuple[str, ...]:
    _, ausgabe = _run("/usr/bin/lipo", "-info", str(pfad))
    if "is architecture:" in ausgabe:
        return (ausgabe.rsplit("is architecture:", 1)[1].strip(),)
    if "are:" in ausgabe:
        return tuple(ausgabe.rsplit("are:", 1)[1].split())
    return ()


def verify_binary(pfad: Path, spec: BinarySpec, *, entitlements_dir: Path,
                  expected_leaf: str | None = None,
                  expected_arch: str | None = None) -> list[Finding]:
    """Alle Einzelnachweise für ein Mach-O. Kein `--deep`, keine Sammelaussage."""
    befunde: list[Finding] = []

    if not pfad.is_file():
        return [Finding(spec.name, "vorhanden", "Datei im Bundle",
                        "fehlt", False)]

    fakten = signature_facts(pfad)
    dr = designated_requirement(pfad)
    blatt = leaf_of(dr)

    befunde.append(Finding(
        spec.name, "identifier", spec.identifier,
        fakten["identifier"], fakten["identifier"] == spec.identifier))

    # Adhoc ist kein „schwächeres Zertifikat", sondern gar keines: Die Bindung
    # haengt am Codehash und ueberlebt keinen Neubau — die einmal erteilte
    # TCC-Berechtigung waere danach weg.
    adhoc = (fakten["signature"] == "adhoc" or "adhoc" in fakten["flags"])
    befunde.append(Finding(
        spec.name, "signatur", "zertifikatsgebunden",
        "adhoc" if adhoc else (fakten["authority"] or "keine Autoritaet"),
        not adhoc and bool(fakten["authority"])))

    befunde.append(Finding(
        spec.name, "hardened-runtime", "runtime",
        fakten["flags"] or "keine", "runtime" in fakten["flags"]))

    befunde.append(Finding(
        spec.name, "dr-zertifikatsgebunden", "certificate leaf",
        dr or "keine", bool(blatt) and "cdhash" not in dr))

    befunde.append(Finding(
        spec.name, "dr-identifier", f'identifier "{spec.identifier}"',
        dr or "keine", f'identifier "{spec.identifier}"' in dr))

    if expected_leaf:
        befunde.append(Finding(
            spec.name, "blatt", expected_leaf.lower(), blatt or "keins",
            blatt == expected_leaf.lower()))

    soll = expected_entitlement_keys(entitlements_dir / spec.entitlements_file)
    ist = entitlement_keys(pfad)
    befunde.append(Finding(
        spec.name, "entitlements", ",".join(sorted(soll)) or "(leer)",
        ",".join(sorted(ist)) or "(leer)", ist == soll))

    if expected_arch:
        gemessen = architectures(pfad)
        befunde.append(Finding(
            spec.name, "architektur", expected_arch,
            ",".join(gemessen) or "keine", gemessen == (expected_arch,)))

    return befunde


def verify_app(app: Path, *, entitlements_dir: Path,
               expected_leaf: str | None = None,
               expected_triple: str | None = None,
               specs: tuple[BinarySpec, ...] = BUNDLE_SPECS) -> list[Finding]:
    """Das ganze Bundle, Binary für Binary.

    Ohne `expected_leaf` wird verlangt, dass **alle** Binaries dasselbe Blatt
    nennen: Ein Bundle, dessen Teile aus verschiedenen Zertifikaten stammen,
    ist keines.
    """
    arch = _TRIPLE_ARCH.get(expected_triple or "", None)
    befunde: list[Finding] = []
    macos = app / "Contents" / "MacOS"
    for spec in specs:
        befunde += verify_binary(macos / spec.name, spec,
                                 entitlements_dir=entitlements_dir,
                                 expected_leaf=expected_leaf,
                                 expected_arch=arch)

    blaetter = {leaf_of(designated_requirement(macos / s.name))
                for s in specs if (macos / s.name).is_file()}
    blaetter.discard("")
    befunde.append(Finding(
        "bundle", "einheitliches-blatt", "genau eins",
        ",".join(sorted(blaetter)) or "keins", len(blaetter) == 1))
    return befunde


def format_findings(befunde: list[Finding]) -> str:
    return "\n".join(str(b) for b in befunde)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Prüft den Signatur- und Entitlementvertrag eines "
                    "gepackten Jarvis-Bundles.")
    p.add_argument("app", type=Path, help="Pfad zur .app")
    p.add_argument("--entitlements-dir", type=Path, required=True,
                   help="Verzeichnis mit den .entitlements-Dateien")
    p.add_argument("--expect-leaf", default=None,
                   help="SHA-1 des erwarteten Zertifikatsblatts")
    p.add_argument("--expect-triple", default=None,
                   help="Rust-Triple der Zielarchitektur")
    args = p.parse_args(argv)

    befunde = verify_app(args.app, entitlements_dir=args.entitlements_dir,
                         expected_leaf=args.expect_leaf,
                         expected_triple=args.expect_triple)
    print(format_findings(befunde))
    verletzt = [b for b in befunde if not b.ok]
    if verletzt:
        print(f"\nVERTRAGSBRUCH: {len(verletzt)} von {len(befunde)} "
              f"Nachweisen fehlgeschlagen.")
        return 1
    print(f"\nVERTRAG ERFUELLT: {len(befunde)} Nachweise.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

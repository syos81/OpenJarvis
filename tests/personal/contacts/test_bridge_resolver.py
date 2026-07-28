"""Binary-Resolver der Native-Bridge (Plan §15).

Kontaktfrei: es wird **nichts ausgeführt**. Geprüft werden ausschliesslich
Pfad-, Architektur- und Identitätsregeln — auch beim arm64-Binary, das auf
einem Intel-Host niemals gestartet wird.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from personaljarvis.contacts.bridge.errors import BridgeConfigurationError
from personaljarvis.contacts.bridge.resolver import (
    BINARY_NAME,
    binary_architectures,
    host_architecture,
    resolve_sidecar,
    tauri_triple,
)

_REPO = Path(__file__).resolve().parents[3]
_NATIVE = _REPO / "native" / "contacts-bridge"


def _built(arch: str) -> Path | None:
    """Ein bereits gebautes Binary, falls vorhanden — es wird nie gebaut."""
    candidates = {
        "x86_64": _NATIVE / "build" / BINARY_NAME,
        "arm64": _NATIVE / "build-arm64" / BINARY_NAME,
    }
    path = candidates[arch]
    return path if path.exists() else None


# ── Architektur- und Namenskonventionen ─────────────────────────────────────
def test_host_architektur_ist_bekannt():
    assert host_architecture() in ("x86_64", "arm64")


def test_tauri_triple_je_architektur():
    assert tauri_triple("arm64") == "aarch64-apple-darwin"
    assert tauri_triple("x86_64") == "x86_64-apple-darwin"


# ── Injizierter Testpfad ────────────────────────────────────────────────────
def test_nativer_pfad_wird_aufgeloest():
    native = _built(host_architecture())
    if native is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    location = resolve_sidecar(native)
    assert location.path == native
    assert host_architecture() in location.architectures


def test_fremde_architektur_ist_konfigurationsfehler():
    """Ein arm64-Binary auf Intel wird abgelehnt — nie ausgefuehrt."""
    other = "arm64" if host_architecture() == "x86_64" else "x86_64"
    foreign = _built(other)
    if foreign is None:
        pytest.skip(f"{other}-Sidecar nicht gebaut")
    with pytest.raises(BridgeConfigurationError, match="Architektur"):
        resolve_sidecar(foreign)


def test_fremde_architektur_statisch_pruefbar():
    """Die statische Architekturangabe ist auch ohne Ausfuehrung lesbar."""
    other = "arm64" if host_architecture() == "x86_64" else "x86_64"
    foreign = _built(other)
    if foreign is None:
        pytest.skip(f"{other}-Sidecar nicht gebaut")
    assert other in binary_architectures(foreign)


def test_fehlende_datei_ist_konfigurationsfehler(tmp_path):
    with pytest.raises(BridgeConfigurationError, match="nicht gefunden"):
        resolve_sidecar(tmp_path / "gibt-es-nicht")


def test_nicht_ausfuehrbare_datei_wird_abgelehnt(tmp_path):
    f = tmp_path / BINARY_NAME
    f.write_bytes(b"\x00")
    f.chmod(0o600)
    with pytest.raises(BridgeConfigurationError, match="ausfuehrbar"):
        resolve_sidecar(f)


def test_kein_macho_wird_abgelehnt(tmp_path):
    f = tmp_path / BINARY_NAME
    f.write_text("#!/bin/sh\necho hi\n")
    f.chmod(0o755)
    with pytest.raises(BridgeConfigurationError):
        resolve_sidecar(f)


def test_symlink_wird_fail_closed_abgelehnt(tmp_path):
    native = _built(host_architecture())
    if native is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    link = tmp_path / BINARY_NAME
    link.symlink_to(native)
    with pytest.raises(BridgeConfigurationError, match="[Ss]ymlink"):
        resolve_sidecar(link)


def test_kein_pfad_konfiguriert_ist_fehler(monkeypatch):
    monkeypatch.delenv("PERSONAL_JARVIS_CONTACTS_SIDECAR", raising=False)
    with pytest.raises(BridgeConfigurationError, match="Kein Sidecar-Pfad"):
        resolve_sidecar()


def test_umgebungspfad_wird_verwendet(monkeypatch, tmp_path):
    monkeypatch.setenv("PERSONAL_JARVIS_CONTACTS_SIDECAR", str(tmp_path / "fehlt"))
    with pytest.raises(BridgeConfigurationError, match="nicht gefunden"):
        resolve_sidecar()


def test_bundlepfad_wird_geprueft(tmp_path):
    native = _built(host_architecture())
    if native is None:
        pytest.skip("nativer Sidecar nicht gebaut")
    bundle = tmp_path / "MacOS"
    bundle.mkdir()
    shutil.copy2(native, bundle / BINARY_NAME)
    location = resolve_sidecar(bundle_dir=bundle)
    assert location.path == bundle / BINARY_NAME


# ── Keine Spike-Abhängigkeit ────────────────────────────────────────────────
def test_produktivcode_haengt_nicht_an_spikes():
    """Kein Produktmodul darf `spikes/` importieren oder referenzieren.

    Geprueft werden **echte Bezuege** — Importe, Pfadangaben, Spike-Praefixe —,
    nicht die blosse Erwaehnung des Wortes in einer Abgrenzungsnotiz.
    """
    src = _REPO / "src" / "personaljarvis"
    treffer = []
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for muster in ("import spikes", "from spikes", '"spikes/', "'spikes/",
                       "contacts-bridge-g3a", "ZZZ-JarvisTest-",
                       "JarvisContactsSpike"):
            if muster in text:
                treffer.append(f"{path.relative_to(_REPO)}: {muster}")
    assert not treffer, f"Spike-Bezug im Produktcode: {treffer}"

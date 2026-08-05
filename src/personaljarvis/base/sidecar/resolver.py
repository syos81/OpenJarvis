"""Auflösung eines Sidecar-Binarys (Ollama-Präzedenzfall).

Gehoben aus `contacts.bridge.resolver` (2026-08-04). Kontaktspezifisch waren
daran nur der Binärname und die Umgebungsvariable — beide sind jetzt
Parameter.

Verbindlich:

* **Kein absoluter Entwicklungspfad** im Code; jeder Ort kommt aus der
  Konfiguration oder aus `current_exe()`-nahen Bundle-Pfaden.
* **Kein Download, keine Laufzeitkompilierung**, keine Abhängigkeit auf
  `spikes/` — ein Spike ist Referenz, nie Laufzeitbestandteil.
* Die Host-Architektur muss zum Binary passen. Ein arm64-Binary auf einem
  Intel-Host ist ein **Konfigurationsfehler**, kein Laufzeitversuch.
* Symlinks werden fail-closed abgelehnt: ein austauschbarer Pfad wäre eine
  Umgehung der Architektur- und Identitätsprüfung.

Die Schnittstelle trägt getrennte Architektur-Binaries **und** ein späteres
Universal-2-Artefakt, ohne DEC-D17 vorwegzunehmen: geprüft wird, ob das Binary
die Host-Architektur **enthält**, nicht ob es ausschließlich sie enthält.
"""

from __future__ import annotations

import os
import platform
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from personaljarvis.base.sidecar.errors import BridgeConfigurationError

__all__ = [
    "host_architecture",
    "tauri_triple",
    "binary_architectures",
    "SidecarLocation",
    "resolve_sidecar",
]

_SUPPORTED_ARCHITECTURES = ("x86_64", "arm64")


def host_architecture() -> str:
    """Architektur des laufenden Prozesses (`arm64` oder `x86_64`)."""
    machine = platform.machine()
    return "arm64" if machine in ("arm64", "aarch64") else machine


def tauri_triple(architecture: str | None = None) -> str:
    """Der von Tauri erwartete `externalBin`-Suffix einer Architektur."""
    arch = architecture or host_architecture()
    return {"arm64": "aarch64-apple-darwin",
            "x86_64": "x86_64-apple-darwin"}.get(arch, arch)


def binary_architectures(path: Path) -> tuple[str, ...]:
    """Alle im Mach-O enthaltenen Architekturen laut `lipo -info`.

    Ein Universal-2-Artefakt liefert mehrere Einträge — die Prüfung bleibt
    damit formatunabhängig (DEC-D17 wird nicht vorweggenommen).
    """
    try:
        proc = subprocess.run(
            ["/usr/bin/lipo", "-info", str(path)],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeConfigurationError(
            f"Architektur nicht bestimmbar: {exc.__class__.__name__}"
        ) from exc
    out = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise BridgeConfigurationError("Datei ist kein Mach-O-Binary")
    if "are:" in out:                       # Fat/Universal
        return tuple(out.split("are:", 1)[1].split())
    if "architecture:" in out:              # Thin
        return (out.split("architecture:", 1)[1].strip(),)
    raise BridgeConfigurationError("Architekturangabe nicht auswertbar")


@dataclass(frozen=True)
class SidecarLocation:
    """Ein geprüfter, ausführbarer Sidecar-Pfad."""

    path: Path
    architectures: tuple[str, ...]
    host_architecture: str

    @property
    def is_universal(self) -> bool:
        return len(self.architectures) > 1


def _candidate_paths(explicit: Path | None, bundle_dir: Path | None,
                     binary_name: str, env_var: str) -> list[Path]:
    """Suchreihenfolge — ausschließlich injizierte bzw. Bundle-Pfade."""
    if explicit is not None:
        return [explicit]

    candidates: list[Path] = []
    # 1. Ausdrückliche Konfiguration über die Umgebung (Test- und Betriebsweg).
    from_env = os.environ.get(env_var)
    if from_env:
        candidates.append(Path(from_env))
    # 2. Gepackte App: der Sidecar liegt neben der ausführbaren Datei.
    if bundle_dir is not None:
        candidates.append(bundle_dir / binary_name)
        candidates.append(bundle_dir / f"{binary_name}-{tauri_triple()}")
    return candidates


def resolve_sidecar(
    binary_name: str,
    env_var: str,
    explicit_path: Path | str | None = None,
    *,
    bundle_dir: Path | str | None = None,
    require_host_architecture: bool = True,
    architectures_of: Callable[[Path], tuple[str, ...]] | None = None,
) -> SidecarLocation:
    """Findet und prüft ein Sidecar-Binary — fail-closed.

    `explicit_path` ist der injizierbare Testpfad und hat Vorrang vor allem
    anderen. Es wird **nichts** heruntergeladen und **nichts** kompiliert.

    `architectures_of` ist der Einhängepunkt der Architekturprüfung. Er
    existiert, damit ein Modul-Wrapper seine **eigene** Prüffunktion
    durchreichen kann: Tests ersetzen dort eine Attrappe, und der
    Auflösungsweg selbst bleibt trotzdem der produktive.
    """
    explicit = Path(explicit_path) if explicit_path is not None else None
    bundle = Path(bundle_dir) if bundle_dir is not None else None
    candidates = _candidate_paths(explicit, bundle, binary_name, env_var)
    if not candidates:
        raise BridgeConfigurationError(
            "Kein Sidecar-Pfad konfiguriert (weder explizit, noch Umgebung, "
            "noch Bundle-Verzeichnis)"
        )

    found: Path | None = None
    for cand in candidates:
        if cand.exists():
            found = cand
            break
    if found is None:
        raise BridgeConfigurationError(
            f"Sidecar-Binary nicht gefunden ({len(candidates)} Pfade geprueft)"
        )

    # Symlinks fail-closed: ein umhängbarer Pfad unterliefe die Architektur-
    # und Identitätsprüfung.
    if found.is_symlink():
        raise BridgeConfigurationError("Sidecar-Pfad ist ein Symlink — abgelehnt")
    resolved = found.resolve()
    if resolved != found.absolute():
        raise BridgeConfigurationError(
            "Sidecar-Pfad enthaelt einen Symlink im Verlauf — abgelehnt"
        )
    if not stat.S_ISREG(found.lstat().st_mode):
        raise BridgeConfigurationError("Sidecar-Pfad ist keine regulaere Datei")
    if not os.access(found, os.X_OK):
        raise BridgeConfigurationError("Sidecar-Binary ist nicht ausfuehrbar")

    architectures = (architectures_of or binary_architectures)(found)
    host = host_architecture()
    if require_host_architecture and host not in architectures:
        raise BridgeConfigurationError(
            f"Sidecar-Architektur passt nicht zum Host: Binary {architectures}, "
            f"Host {host}. Ein fremdarchitektonisches Binary wird nicht "
            f"ausgefuehrt (Rosetta ist kein Abnahmeweg)."
        )
    for arch in architectures:
        if arch not in _SUPPORTED_ARCHITECTURES:
            raise BridgeConfigurationError(
                f"Nicht unterstuetzte Architektur im Binary: {arch}"
            )
    return SidecarLocation(path=found, architectures=architectures,
                           host_architecture=host)

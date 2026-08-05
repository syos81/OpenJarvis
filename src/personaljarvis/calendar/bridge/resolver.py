"""Auflösung des Kalender-Sidecar-Binarys.

Die Prüfungen selbst sind gemeinsam (`base.sidecar.resolver`): kein Download,
keine Laufzeitkompilierung, keine `spikes/`-Abhängigkeit, Symlinks fail-closed,
Host-Architektur muss enthalten sein. Hier steht nur die Bindung an das
Kalender-Binary.
"""

from __future__ import annotations

from pathlib import Path

from personaljarvis.base.sidecar.resolver import (
    SidecarLocation,
    binary_architectures,
    host_architecture,
    tauri_triple,
)
from personaljarvis.base.sidecar.resolver import (
    resolve_sidecar as _resolve_sidecar,
)

__all__ = [
    "BINARY_NAME",
    "SIDECAR_ENV_VAR",
    "host_architecture",
    "tauri_triple",
    "binary_architectures",
    "SidecarLocation",
    "resolve_sidecar",
]

#: Basisname des Sidecars. Der Tauri-`externalBin`-Mechanismus hängt beim
#: Bündeln das Ziel-Triple an; im Bundle liegt wieder der Basisname.
BINARY_NAME = "jarvis-calendar"

#: Ausdrückliche Pfadkonfiguration (Test- und Betriebsweg).
SIDECAR_ENV_VAR = "PERSONAL_JARVIS_CALENDAR_SIDECAR"


def resolve_sidecar(
    explicit_path: Path | str | None = None,
    *,
    bundle_dir: Path | str | None = None,
    require_host_architecture: bool = True,
) -> SidecarLocation:
    """Findet und prüft das Kalender-Sidecar-Binary — fail-closed."""
    # `binary_architectures` bewusst als Modul-Global durchgereicht: Tests
    # ersetzen genau diesen Namen hier, der Auflösungsweg bleibt der produktive.
    return _resolve_sidecar(
        BINARY_NAME, SIDECAR_ENV_VAR, explicit_path,
        bundle_dir=bundle_dir,
        require_host_architecture=require_host_architecture,
        architectures_of=lambda path: binary_architectures(path),
    )

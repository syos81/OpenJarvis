"""Der Abhängigkeitsvertrag des Desktop-Starts. **Kontaktfrei.**

Hintergrund: `uv sync --extra desktop` war auf diesem Intel-Mac nicht
installierbar. Das `desktop`-Extra zog `faster-whisper`, das `onnxruntime`
verlangt — und dessen Wheels beginnen bei `macosx_14_0_arm64`. Für macOS
x86_64 existiert **kein** Wheel und keine Quelldistribution; für Apple Silicon
erst ab macOS 14, obwohl dieses Projekt macOS 12.3 als Untergrenze zusagt
(ADR-0018). Der Start der App scheiterte daran vollständig — samt Kontakte,
API und Read-Sync, die kein Modell und keine Spracherkennung brauchen.

Diese Datei prüft den Vertrag statisch gegen `pyproject.toml` und `uv.lock`.
Sie startet nichts, lädt nichts nach und berührt keinen Kontakt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import tomllib

_REPO = Path(__file__).resolve().parents[3]
_PYPROJECT = _REPO / "pyproject.toml"
_LOCK = _REPO / "uv.lock"

#: Die Extras, die der Desktop-Startpfad synchronisiert. Wortgleich zu
#: `DESKTOP_BASE_SYNC_ARGS` und `INFERENCE_SYNC_ARGS` in `lib.rs`.
DESKTOP_START_EXTRAS = ("desktop",)
INFERENCE_EXTRAS = ("inference-cloud", "inference-google")

#: Produktive Zielplattformen (DEC-042, ADR-0018 für macOS; Linux als
#: Serverziel).
ZIELPLATTFORMEN = (
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-unknown-linux-gnu",
)


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lock() -> dict:
    return tomllib.loads(_LOCK.read_text(encoding="utf-8"))


def _extras(pyproject: dict) -> dict[str, list[str]]:
    return pyproject["project"]["optional-dependencies"]


def _paket(lock: dict, name: str) -> dict | None:
    for eintrag in lock.get("package", []):
        if eintrag.get("name") == name:
            return eintrag
    return None


# ── Der Vertrag selbst ──────────────────────────────────────────────────────
def test_desktop_extra_verlangt_keine_spracherkennung(pyproject):
    """Spracherkennung ist eine Fähigkeit, keine Startvoraussetzung."""
    desktop = _extras(pyproject)["desktop"]
    assert not any("faster-whisper" in d for d in desktop), desktop


def test_spracherkennung_bleibt_als_eigenes_extra_erhalten(pyproject):
    """Entfernt wurde die Kopplung, nicht die Fähigkeit."""
    assert any("faster-whisper" in d for d in _extras(pyproject)["speech"])


def test_desktop_extra_traegt_weiter_seine_laufzeit(pyproject):
    """Was der Desktop wirklich braucht, bleibt drin."""
    desktop = " ".join(_extras(pyproject)["desktop"])
    for pflicht in ("fastapi", "uvicorn", "pydantic", "python-multipart"):
        assert pflicht in desktop, pflicht


def test_lock_spiegelt_den_vertrag(lock):
    """Der Lock ist nachgezogen — sonst installiert `--frozen` das Alte."""
    eigen = _paket(lock, "openjarvis")
    assert eigen is not None
    desktop = eigen["optional-dependencies"]["desktop"]
    namen = {d["name"] for d in desktop}
    assert "faster-whisper" not in namen, namen
    assert {"fastapi", "uvicorn", "pydantic", "python-multipart"} <= namen


# ── Die Ursache, festgenagelt ───────────────────────────────────────────────
def test_onnxruntime_hat_kein_macos_x86_64_wheel(lock):
    """Der Grund für den Vertrag — und ein Wächter, falls er entfällt.

    Liefert Upstream irgendwann ein macOS-x86_64-Wheel, schlägt dieser Test
    fehl und sagt damit: die Beschränkung ist weg, die Entscheidung kann neu
    getroffen werden. Ein stiller Fortbestand wäre schlechter.
    """
    onnx = _paket(lock, "onnxruntime")
    if onnx is None:
        pytest.skip("onnxruntime ist nicht mehr im Lock")
    wheels = [w["url"].rsplit("/", 1)[-1] for w in onnx.get("wheels", [])]
    macos_x86 = [w for w in wheels if "macosx" in w and "x86_64" in w]
    assert macos_x86 == [], macos_x86
    assert "sdist" not in onnx, "es gibt eine Quelldistribution — bitte neu bewerten"


def test_onnxruntime_haengt_nur_an_der_spracherkennung(lock):
    """Sonst wäre das Extra nicht der richtige Ort für die Entscheidung."""
    verlangt = {
        p["name"] for p in lock.get("package", [])
        if p.get("name") != "onnxruntime"
        and any(d.get("name") == "onnxruntime" for d in p.get("dependencies", []))
    }
    assert verlangt == {"faster-whisper"}, verlangt


# ── Der Startpfad zieht es nicht herein ─────────────────────────────────────
def _huelle(lock: dict, wurzeln: set[str]) -> set[str]:
    """Transitive Abhängigkeitshülle über den Lock, plattformunabhängig."""
    nach_name = {p["name"]: p for p in lock.get("package", [])}
    offen, gesehen = list(wurzeln), set()
    while offen:
        name = offen.pop()
        if name in gesehen:
            continue
        gesehen.add(name)
        paket = nach_name.get(name)
        if paket is None:
            continue
        for d in paket.get("dependencies", []):
            offen.append(d["name"])
        for gruppe in paket.get("optional-dependencies", {}).values():
            for d in gruppe:
                offen.append(d["name"])
    return gesehen


def test_startpfad_zieht_kein_onnxruntime(lock):
    """Weder der degradierte noch der konfigurierte Startpfad."""
    eigen = _paket(lock, "openjarvis")
    for extras in (DESKTOP_START_EXTRAS, DESKTOP_START_EXTRAS + INFERENCE_EXTRAS):
        wurzeln = {
            d["name"]
            for extra in extras
            for d in eigen["optional-dependencies"].get(extra, [])
        }
        huelle = _huelle(lock, wurzeln)
        assert "onnxruntime" not in huelle, (extras, sorted(huelle)[:20])


def test_startpfad_fordert_das_speech_extra_nicht(lock):
    """`speech` bleibt ausdrücklicher Wunsch, nie Nebenwirkung des Starts."""
    eigen = _paket(lock, "openjarvis")
    speech = {d["name"] for d in eigen["optional-dependencies"]["speech"]}
    desktop = {d["name"] for d in eigen["optional-dependencies"]["desktop"]}
    assert not (speech & desktop), speech & desktop


# ── Auflösbarkeit auf allen Zielplattformen ─────────────────────────────────
@pytest.mark.parametrize("plattform", ZIELPLATTFORMEN)
def test_startpfad_ist_auf_jeder_zielplattform_aufloesbar(plattform):
    """`uv sync --dry-run` je Plattform — ohne Netz, ohne Installation.

    `--frozen` verbietet ein Nachlocken; scheitert die Auflösung, ist der Lock
    für diese Plattform kaputt und der App-Start dort unmöglich.
    """
    if not (_REPO / "uv.lock").exists():  # pragma: no cover
        pytest.skip("kein Lock vorhanden")
    proc = subprocess.run(
        ["uv", "sync", "--frozen", "--extra", "desktop",
         "--extra", "inference-cloud", "--extra", "inference-google",
         "--group", "desktop-native",
         "--python-platform", plattform, "--dry-run"],
        cwd=_REPO, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "onnxruntime" not in proc.stdout, "onnxruntime wuerde installiert"


def test_lock_und_pyproject_sind_deckungsgleich():
    """Ein nicht nachgezogener Lock würde den alten Vertrag installieren."""
    proc = subprocess.run(["uv", "lock", "--check"], cwd=_REPO,
                          capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stderr[-1500:]

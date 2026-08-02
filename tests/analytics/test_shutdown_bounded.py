"""Der Analytics-Shutdown blockiert nie unbegrenzt. **Netz- und datenfrei.**

Anlass (2026-08-02, x86_64/macOS 12.7.6): Nach SIGTERM gab `jarvis serve`
Port 8000 sofort frei, der ASGI-Lifespan hing danach aber in
`_shutdown_analytics` → `posthog.Client.shutdown()` → `Thread.join()` ohne
Timeout, während der posthog-Consumer in `queue.get()` bis zu
`flush_interval` (30 s) auf das nächste Event wartete. Der Desktop musste
den Prozess deshalb regelmäßig nach 8 s per SIGKILL beenden; die direkte
Reproduktion ohne Tauri lebte über 20 s.

Der Fix verlagert Flush+SDK-Shutdown in einen daemon-Trägerthread mit
fester Frist (`AnalyticsClient.SHUTDOWN_TIMEOUT_SECONDS`). Diese Tests
halten den Vertrag fest — mit einem Fake-SDK, dessen `shutdown()` absichtlich
unbegrenzt blockiert: exakt das belegte Fehlerbild.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from openjarvis.analytics.client import AnalyticsClient

_REPO = Path(__file__).resolve().parents[2]


class BlockierendesSdk:
    """Fake-posthog: `shutdown()` blockiert wie der 30-s-Consumer-Join."""

    def __init__(self, *, block_shutdown: bool = True,
                 raise_on_flush: bool = False) -> None:
        self.block_shutdown = block_shutdown
        self.raise_on_flush = raise_on_flush
        self.flush_calls = 0
        self.shutdown_calls = 0
        self.release = threading.Event()

    def flush(self) -> None:
        self.flush_calls += 1
        if self.raise_on_flush:
            raise RuntimeError("flush kaputt")

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.block_shutdown:
            # Unbegrenzt wie der echte Join auf den queue.get-Consumer.
            self.release.wait()


def _client_mit(sdk) -> AnalyticsClient:
    client = AnalyticsClient.__new__(AnalyticsClient)
    client._lock = threading.Lock()
    client._posthog = sdk
    client._enabled = True
    return client


def _threads_vorher() -> set[int]:
    return {t.ident for t in threading.enumerate()}


# ═══ A · Rot-Reproduktion des alten Verhaltens ══════════════════════════════
def test_a_ohne_frist_wuerde_der_blockierende_join_haengen():
    """Das Fehlerbild selbst: ein direkter Aufruf des SDK-Shutdowns kehrt
    nicht zurück, solange niemand den Consumer weckt."""
    sdk = BlockierendesSdk()
    direkt = threading.Thread(target=sdk.shutdown, daemon=True)
    direkt.start()
    direkt.join(timeout=0.5)
    assert direkt.is_alive(), "der rohe SDK-Shutdown blockiert (Fehlerbild)"
    sdk.release.set()
    direkt.join(timeout=2)
    assert not direkt.is_alive()


# ═══ B · Begrenzter Shutdown trotz blockierendem SDK ════════════════════════
def test_b_shutdown_kehrt_innerhalb_der_frist_zurueck():
    sdk = BlockierendesSdk()
    client = _client_mit(sdk)
    t0 = time.monotonic()
    client.shutdown()
    dauer = time.monotonic() - t0
    grenze = AnalyticsClient.SHUTDOWN_TIMEOUT_SECONDS
    assert dauer < grenze + 1.0, f"{dauer:.2f}s"
    assert dauer >= grenze - 0.1          # er hat den Flushversuch abgewartet
    assert sdk.flush_calls == 1
    assert sdk.shutdown_calls == 1
    assert client._posthog is None
    sdk.release.set()


def test_b2_schneller_shutdown_wartet_nicht_die_volle_frist():
    sdk = BlockierendesSdk(block_shutdown=False)
    client = _client_mit(sdk)
    t0 = time.monotonic()
    client.shutdown()
    assert time.monotonic() - t0 < 0.5
    assert sdk.shutdown_calls == 1


# ═══ C/H · Kein Leak: der Träger ist daemon und hält nichts ═════════════════
def test_c_traeger_ist_daemon_und_kein_non_daemon_rest():
    sdk = BlockierendesSdk()
    client = _client_mit(sdk)
    vorher = _threads_vorher()
    client.shutdown()
    neue = [t for t in threading.enumerate() if t.ident not in vorher]
    for t in neue:
        assert t.daemon, f"non-daemon Restthread: {t.name}"
    assert any(t.name == "analytics-shutdown" for t in neue)
    sdk.release.set()
    time.sleep(0.1)


# ═══ D · Idempotenz ═════════════════════════════════════════════════════════
def test_d_zweiter_shutdown_ist_noop():
    sdk = BlockierendesSdk(block_shutdown=False)
    client = _client_mit(sdk)
    client.shutdown()
    client.shutdown()
    assert sdk.flush_calls == 1
    assert sdk.shutdown_calls == 1


# ═══ E · Teilfehler verhindert den Abschluss nicht ══════════════════════════
def test_e_flush_fehler_verhindert_sdk_shutdown_nicht():
    sdk = BlockierendesSdk(block_shutdown=False, raise_on_flush=True)
    client = _client_mit(sdk)
    client.shutdown()                      # darf nicht werfen
    assert sdk.shutdown_calls == 1
    assert client._posthog is None


# ═══ F · Bereits geschlossen ════════════════════════════════════════════════
def test_f_bereits_geschlossen_ist_kein_fehler():
    client = AnalyticsClient.__new__(AnalyticsClient)
    client._lock = threading.Lock()
    client._posthog = None
    client._enabled = False
    client.shutdown()                      # kein Fehler, kein Aufruf


# ═══ G · Lifespan-Aufrufstelle bleibt fehlertolerant ════════════════════════
def test_g_lifespan_ruft_shutdown_in_try_except():
    quelle = (_REPO / "src/openjarvis/server/app.py").read_text()
    idx = quelle.index("client.shutdown()")
    umgebung = quelle[max(0, idx - 200):idx + 100]
    assert "try:" in umgebung
    assert "except Exception" in umgebung


# ═══ I · Desktop-Regression: Fallback und Menü-Umleitung bleiben ════════════
def test_i_desktop_sigkill_fallback_und_menu_quit_bleiben():
    shutdown_rs = (_REPO / "frontend/src-tauri/src/backend_shutdown.rs").read_text()
    assert "SIGKILL" in shutdown_rs
    assert "TERM_TIMEOUT" in shutdown_rs
    lib_rs = (_REPO / "frontend/src-tauri/src/lib.rs").read_text()
    assert '"app-quit"' in lib_rs          # Menü-Umleitung aus d6615a2
    assert "app.exit(0)" in lib_rs


# ═══ J · Isolation ══════════════════════════════════════════════════════════
def test_j_kein_netz_und_keine_daten_beruehrt():
    """Der Fake ersetzt das SDK vollständig; ein Netz-Zugriff wäre ein
    Aufruf am Fake vorbei und damit ein zusätzlicher shutdown_call."""
    sdk = BlockierendesSdk(block_shutdown=False)
    client = _client_mit(sdk)
    client.shutdown()
    assert sdk.shutdown_calls == 1


# ═══ Statik: die Frist ist dokumentiert und begrenzt ════════════════════════
def test_die_frist_ist_klein_und_dokumentiert():
    assert 0.5 <= AnalyticsClient.SHUTDOWN_TIMEOUT_SECONDS <= 3.0
    quelle = (_REPO / "src/openjarvis/analytics/client.py").read_text()
    assert "daemon=True" in quelle.split("def shutdown")[1]
    assert "join(timeout=" in quelle.split("def shutdown")[1]

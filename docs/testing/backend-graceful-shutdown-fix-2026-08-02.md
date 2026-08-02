# Backend-Graceful-Shutdown-Fix (x86_64), 2026-08-02

Branch `fix/backend-graceful-shutdown-2026-08-02`, Basis `d6615a2`, isolierter
Worktree. Kein Contacts-Code berührt; der Desktop-SIGKILL-Fallback (8 s)
bleibt unverändert als letztes Netz bestehen.

## Ausgangsbefund

Aus dem Lifecycle- und Menü-Quit-Fix belegt: Nach SIGTERM gibt `jarvis serve`
den Port sofort frei, der Prozess lebt aber regelmäßig länger als die
8-s-Frist des Desktops und wird per SIGKILL beendet. Zwei frühere Hypothesen
wurden dabei **widerlegt** (instrumentierte Traces): weder blockiert der
tokio-Poll-Loop noch halten offene HTTP-Verbindungen oder ein Zombie-Zustand
den Prozess — der Python-Prozess selbst quittiert den TERM-Teardown nicht.

## Direkte Reproduktion ohne Tauri

Eigenes Repro-Skript (außerhalb des Repos): `jarvis serve` in eigener
Prozessgruppe mit Wegwerf-`HOME`/-Datenbank auf freiem Port, SIGTERM an die
Gruppe, monotone Zeitmessung. **Vorher:** Port nach ~0,1 s frei, Prozess nach
über 20 s noch am Leben (Messabbruch). **Nachher:** Prozessende nach
1,65–1,74 s — drei Läufe in Folge, nur SIGTERM, kein manuelles Signal.

## Eigentümer-Beweis (Stacks, nicht Vermutung)

Per env-gatetem `faulthandler.register(SIGUSR1, all_threads=True)`
(`OPENJARVIS_SHUTDOWN_DIAGNOSTICS=1`, standardmäßig aus) zwei Dumps bei 3 s
und 7 s nach SIGTERM, beide identisch:

- **Main Thread:** ASGI-Lifespan → `_shutdown_analytics` (`server/app.py`) →
  `analytics/client.py` → posthog `Client.shutdown()` → `Thread.join()`
  **ohne Timeout** → `_wait_for_tstate_lock`.
- **posthog-Consumer:** `queue.get(block=True, timeout=flush_interval - …)`
  — wartet bis zu `flush_interval` auf das nächste Event. Unsere
  Konfiguration setzt `flush_interval_seconds = 30` (`core/config.py`).
- Alle übrigen Restthreads (Agent-Scheduler, Telemetrie-Flusher,
  posthog-Consumer selbst) sind daemon — **einzig der timeoutlose Join
  blockiert** den Prozessausgang, bis zu 30 s lang.

## Die Korrektur (minimal, nur der belegte Eigentümer)

`AnalyticsClient.shutdown()` (`src/openjarvis/analytics/client.py`):

1. Unter dem Lock wird das SDK-Handle atomar ausgehängt (idempotent; ein
   zweiter Aufruf ist ein No-op).
2. `flush()` und SDK-`shutdown()` laufen in einem daemon-Trägerthread
   (`analytics-shutdown`), **einzeln** fehlergesichert — ein Flush-Fehler
   verhindert den SDK-Shutdown nicht.
3. Der Aufrufer joint den Träger mit fester Frist
   (`SHUTDOWN_TIMEOUT_SECONDS = 1.5`). Läuft der Träger weiter, hält er als
   daemon den Prozessausgang nicht mehr auf; im schnellen Normalfall kehrt
   der Aufruf deutlich früher zurück.

Bewusst **nicht** getan: kein `os._exit`, kein SIGKILL aus Python, keine
pauschale Daemonisierung fremder Threads, keine Verkürzung der
Desktop-Frist, keine Änderung am posthog-SDK oder an `flush_interval`.

## Tests

11 neue netz- und datenfreie Tests in `tests/analytics/test_shutdown_bounded.py`
(Fake-SDK, dessen `shutdown()` absichtlich unbegrenzt blockiert): A
Rot-Reproduktion des timeoutlosen Joins; B/B2 Rückkehr innerhalb der Frist
bzw. schneller Normalfall < 0,5 s; C/H nur ein daemon-Trägerthread, kein
non-daemon-Rest; D Idempotenz; E Flush-Fehler verhindert SDK-Shutdown nicht
(deckte im ersten Lauf einen echten Mangel auf — ein gemeinsamer
try-Block — der daraufhin korrigiert wurde); F bereits geschlossen; G
Lifespan-Aufrufstelle bleibt fehlertolerant; I Desktop-Regression
(SIGKILL-Fallback und Menü-Umleitung unangetastet); J Isolation; Statik der
Frist. Volle Gates: analytics+server 364, tests/personal/contacts 956,
tests/personal 983, make test 8218, cargo 63 + rust-Workspace 33 Suiten,
npm 141, tsc, Wheel-Bau + isolierter Import, Ruff scoped = Baseline (80),
mkdocs = 18 vorbestehende Warnungen, `git diff --check` sauber.

## Diagnose-Zugang bleibt erhalten

Der SIGUSR1-Stackdump in `cli/serve.py` bleibt env-gatet
(`OPENJARVIS_SHUTDOWN_DIAGNOSTICS=1`) und ist standardmäßig aus — kein
Verhalten im Normalbetrieb, aber künftige Hänger sind sofort beweisbar.

## Drei Live-Zyklen (x86_64, macOS 12.7.6, Release-Build + Reseal)

Gemessen mit einem rein lesenden Rekorder (ps/lsof, monotone Uhr); Anker
ist die Portfreigabe ~0,1 s nach SIGTERM (aus der direkten Reproduktion
belegt), `Teardown` = Backend-Ende minus Portfreigabe:

| Zyklus | Weg | Teardown | Signal |
|---|---|---|---|
| 0 (Zusatz) | Apple-Event-Quit (osascript) | 1,35 s | SIGTERM |
| 1 | Fenster schließen (Nutzerklick) | 1,55 s | SIGTERM |
| 2 | App-Menü „Quit Jarvis" (Nutzerklick) | 1,73 s | SIGTERM |
| 3 | erneut Start + Menü-Quit (Nutzerklick) | 1,70 s | SIGTERM |

In allen Zyklen: weit unter der 8-s-Frist (der SIGKILL-Fallback feuert
erst bei 8 s — er kam nie zum Zug), Backend vor bzw. mit dem App-Ende
beendet, danach 0 Restprozesse, Port 8000 frei, `serve.lock` entfernt,
kein manuelles Signal. Vor dem Fix endeten die Menü-Quit-Zyklen des
Lifecycle-Fixes regelmäßig erst im 8–9-s-KILL-Fenster.

## Offen

ARM64-Abnahme (nativer Lauf auf Apple Silicon) steht aus — wie beim
Lifecycle- und Menü-Quit-Fix kein Aufschubgrund für den Intel-Fix.

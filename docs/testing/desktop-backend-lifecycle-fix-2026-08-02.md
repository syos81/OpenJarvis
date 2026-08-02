# Backend-Lifecycle-Fix (x86_64), 2026-08-02

Branch `fix/backend-lifecycle-2026-08-02`, Basis `e7b45bd`, isolierter
Worktree. Kein Bezug zum Contacts-AppSave-Spike; Contacts-Code unverändert.

## Bisherige Ursache (belegt)

Aus Code: `ExitRequested` spawnte `stop_all()` nur **asynchron**, ohne den
App-Exit anzuhalten — der Task verlor das Rennen gegen das Prozessende.
`ChildHandle::kill` traf zudem nur das **direkte** Kind (`uv`); `jarvis
serve` läuft als Enkel (`uv → python3`) und überlebte. Aus zehn Live-Läufen
belegt: Der Backendprozess blieb nach jedem App-Ende zurück und musste per
Hand-SIGTERM beendet werden; Port 8000 war danach jeweils frei. Neu belegt
in diesem Fix: **alle zehn** Verwaisungen liefen über das Quit-Apple-Event
(AppleScript/Cmd+Q) — dieser Terminate-Pfad erreichte den
`ExitRequested`-Handler nicht zuverlässig, der Fenster-Pfad schon.

## Die Korrektur

1. **Eigene Unix-Prozessgruppe je Backend-Kind** (`process_group(0)`,
   tokio 1.52): `uv` wird Gruppenleiter (PGID = uv-PID), `python3` erbt die
   Gruppe; Jarvis gehört ihr nie an.
2. **`backend_shutdown::terminate_group`**: SIGTERM an die gespeicherte
   PGID → Warten, bis die *Gruppe* leer ist (Signal 0/ESRCH — deckt Enkel
   ab) → nach fester Frist SIGKILL an exakt dieselbe Gruppe → Leader-Reap.
   `ESRCH` ist überall ein Erfolgszustand. **Frist: 8 s** (uvicorn-Teardown
   braucht real 1–5 s; die App blockiert nie länger als ~10 s gesamt).
3. **Shutdown-Zustandsmaschine** `running → shutting_down → completed`
   (atomar, ohne Rückweg): `ExitRequested` hält den Exit per
   `prevent_exit()` an, fährt genau **einen** Shutdown und setzt den Exit
   danach selbst fort; parallele Close-/Quit-Ereignisse warten idempotent;
   Backendstarts während des Shutdowns werden abgewiesen.
4. **Fangnetz in `RunEvent::Exit`** (synchron/blockierend auf dem Main
   Thread) für Terminate-Pfade, die `ExitRequested` umgehen — genau der
   Apple-Event-Quit. Idempotent über dieselbe Phase.
5. **`serve.lock`** wird nur entfernt, wenn ihre PID **vor** dem Signal
   nachweislich zur eigenen Backendgruppe gehörte (`getpgid`-Abgleich).

**Schutz fremder Prozesse:** Signalisiert wird ausschließlich über die beim
Start gemerkten Gruppen — nie über Prozessnamen, nie per `pkill`, nie über
den Portinhaber (statisch getestet). Ein fremder Inhaber von Port 8000 wird
nie berührt.

## Tests

9 neue kontaktfreie Tests in `backend_shutdown.rs` (eigene
Wegwerf-`/bin/sh`-Kinder, keine Datenbank): eigene Gruppe ohne App (A),
SIGTERM beendet Kind **und Enkel** (B), SIGKILL nach ignoriertem TERM (C),
Idempotenz von Shutdown und Phase (D), bereits beendet (E), kein
Namens-/Port-Kill (F, statisch), Startverbot während Shutdown (G),
Lock-Bereinigung nur für die eigene Gruppe (H). Volle Suiten (I):
cargo 63 (3× stabil), rust-Workspace 33 Suiten, npm 141, tsc, tests/personal
986, make test 8207, Packaging 96, Wheel + isolierter Import, Ruff scoped
= Baseline (80), mkdocs 18 vorbestehende Warnungen.

## Drei Live-Zyklen (x86_64, macOS 12.7.6, Release-Build + Reseal)

| Zyklus | Weg | Backend-Ende | Ergebnis |
|---|---|---|---|
| 1 | Fenster schließen (Nutzerklick) | **1 s** (SIGTERM) | App+uv+python beendet, Port frei, Lock entfernt |
| 2 | App-Menü-Quit (Apple-Event) | 8 s (Frist/KILL-Fenster) | wie oben |
| 3 | erneut Start + Menü-Quit | 9 s | wie oben |

In keinem Zyklus war ein manuelles SIGTERM nötig; zwischen den Zyklen
jeweils 0 Prozesse. Vor dem Fangnetz-Einbau wurde der Apple-Event-Pfad
einmal live rot getestet (Backend überlebte) — dieser Befund führte zur
Korrektur 4.

## Offen

ARM64-Abnahme des Fixes steht aus (nativer Lauf auf Apple Silicon); für den
Intel-Fix ist das kein Aufschubgrund. Die 8-s-Frist beim Menü-Quit endet
teils im KILL-Fenster — funktional korrekt; ob der TERM-Teardown im
blockierten Main-Thread-Kontext langsamer quittiert, kann später separat
verfeinert werden.

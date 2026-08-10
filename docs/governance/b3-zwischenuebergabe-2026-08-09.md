# B3 Zwischenübergabe — P3 DELETE gebaut, Live-Abnahme offen (2026-08-09)

**Dies ist KEIN Abschlussbericht.** B3 ist nicht abgeschlossen: die
Live-Abnahme P3-A steht aus, `platform-live` und `module-final` sind
`blocked` (Live-Record fehlt — ehrlich offen, nicht bestanden). Alle
Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b3-calendar-write.*.json`), Git-Daten und den
committeten deklarativen Artefakten.

## §1 Rahmen und Commits

- Worktree-Regel: immer `git rev-parse --show-toplevel`; Branch
  `spike/calendar-foundation-intel-2026-08-04`.
- Ausgangs-Commit dieser Übergabe: `3b6735a` (B2-Abschluss, Remote-Stand
  vor dem Eigentümer-Push).
- P3-Funktionscommits, jede Erweiterung maschinenlesbar im Commit-Plan
  (`config/gates/history/b3-commit-plan.json`, `plan_change`, kein Amend):
  - Position 7 `b29db20` — DELETE mit drei getrennten, freigabegebundenen
    Nachweisen (9-Feld-Fingerprint, Eligibility-Digest,
    Restore-Preimage-Digest), nativer Re-Read unmittelbar vor Execute,
    Erfolg nur über `absent_confirmed`, Spiegel-Tombstone, Lösch-Dialog.
  - Position 9 `44eb5cc` — Vorbefund vor jedem Live-Versuch: nur explizit
    gesetzte Availability-Markierungen (free/tentative/unavailable) sind
    „belegt"; busy/notSupported/außervokabulare Rohwerte blocken nicht.
  - Position 10 `5bcea4e` — Diagnosereparatur nach erstem abgebrochenem
    P3-A-Versuch: typisierte Probe-Fehlstufen statt stufenlosem null;
    ObjC-JSON→serde-Parse-Pin ergänzt.
  - Position 11 `66e7e0f` — Emissionsreparatur nach zweitem abgebrochenem
    Versuch (Stufe `probe_unparseable`, eigentümergemeldet): Clang boxt
    nackte Vergleichsausdrücke als 0/1-Zahlen; vier Probe-Wahrheitswerte
    laufen jetzt über BOOL-Lokale. Beobachtete Defektemission als
    Muss-Fallen-Regression gepinnt, Quelltext-Wächter gegen geboxte
    Vergleiche, Rohemissions-Erfassung in der Fehlstufe.
- Beide Live-Versuche: **nichts gelöscht, nichts vorbereitet, keine
  Freigabe erteilt** — strukturell belegt: `calendar_mutations` enthält
  keine delete-Zeile (5 create, 1 update).

## §2 Phasen (Enum-Werte aus den maschinellen Berichten, Commit `66e7e0f`)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (7 Checks) |
| targeted | `pass` (4 Checks, inkl. Governance gegen den Remote-Register) |
| offline-final | `pass` (10 Checks) |
| platform-live | `blocked` — `pl-b3-live: live_record_missing` (P3-A offen) |
| module-final | `blocked` — Folge der blockierten Vorphase |

Kein `fail`. `blocked` heisst hier: die Live-Stufen sind ehrlich noch
nicht gelaufen — nicht, dass etwas durchgefallen wäre.

## §3 Merkmalsprüfung (of-feature-lineage, maschinell)

erwartet **281** / zugeordnet **281** / geändert **0** / fehlend **0**;
eigene B3-Merkmale: 16 deklariert (`own_expected`), alle verifiziert —
inkl. der sechs neuen Delete-Merkmale B3-011…B3-016 (Allowlist-Eligibility
vor jeder Mutation, drei gebundene Nachweise mit Re-Read, blocked-Fixtures
mit Zählerbeleg, Offline-Restore über den echten Create-Pfad,
absent_confirmed-Semantik mit Spiegel-Tombstone, Dialog mit sichtbarer
Verweigerung und genau einer Freigabe).

## §4 Der offene Rest: P3-A Live-Abnahme (x86_64-gebunden)

Verbindlich x86_64: das Blockmanifest deklariert
`architectures=["x86_64"]` (Preflight fällt auf arm64 mit
`unsupported_architecture`), das Abnahmeartefakt ist das versiegelte
x86_64-Bundle, TCC-Grant, produktive DB, Backup-Nachweis und
Live-Historie liegen auf dem x86_64-Mac.

Abendablauf am x86_64-Mac (Verifikation, dann ggf. Freigabe):

1. Laufende Jarvis-Instanz beenden; `git pull`; Bundle-Stand prüfen —
   das Bundle unter `frontend/src-tauri/target/x86_64-apple-darwin/
   release/bundle/macos/Jarvis.app` muss aus `66e7e0f` gebaut und mit
   `de.kluender.jarvis` resealed sein (bei Zweifel: neu bauen +
   `APPLE_SIGNING_IDENTITY="de.kluender.jarvis"
   frontend/src-tauri/scripts/reseal-contacts-sidecar.sh <App>`).
2. App starten, Kalender „Aktualisieren", „B3 Update OK" → „Löschen".
3. Erwartung A — VORSCHAU erscheint: Eligibility wurde nativ belegt.
   Dann gilt das vorgelegte P3-A-Protokoll unverändert: gelöscht wird
   ausschliesslich durch den einen Knopf „Löschen freigeben"; der native
   Pfad prüft Fingerprint, Eligibility-Digest und Restore-Digest
   unmittelbar vor dem Remove erneut; danach gemeinsamer produktiver
   Nachweislauf (target „B3 Update OK" absent UND Kontrolle
   „Test Eintrag" present UND read_operation_success), Eigentümer-
   bestätigung Jarvis + Apple, Live-Record, platform-live/module-final.
4. Erwartung B — erneute Verweigerung: die Meldung trägt jetzt Stufe UND
   Rohemission (PII-arm per Konstruktion). Beides wörtlich melden; die
   Rohemission ist der byte-genaue Beleg für die nächste Reparatur.
5. Cleanup „Test Eintrag" erst NACH bestätigtem P3-A; nach heutigem
   Bestand existiert dann kein anderer geeigneter Kontroll-Event →
   voraussichtlich KEIN Cleanup-Delete, „Test Eintrag" bleibt als
   dokumentierte ausstehende Eigentümerbereinigung.

## §5 Was am M2 (arm64) geht — und was nicht

- Geht: Quelltextarbeit auf dem Branch, Rohtestläufe zur Selbstkontrolle
  (`pytest tests/personal/calendar`, `cargo test --lib calendar_write`,
  `vitest run src/personal/calendar` — die Delete-Logik ist gegen
  injizierte Fakes und den Emissions-Parse-Pin getestet; der ObjC-Shim
  kompiliert auch unter arm64).
- Geht NICHT: jede B3-Gatephase (Preflight: `unsupported_architecture`),
  Bundle-Bau fürs Abnahmeartefakt, jede Live-Stufe, jeder produktive
  Kalenderkontakt. Rohtestläufe am M2 sind Selbstkontrolle, nie Evidenz
  DEC-067 (spike/calendar-foundation-intel-2026-08-04, „Der Bericht ist Folge der Definition, nie ihre Schwester").

## §6 Bekannte Umgebungsbefunde (keine Repo-Defekte)

- `uv run jarvis serve` (App-Start) synchronisiert das venv und entfernt
  dabei pytest (dev-Extra). Vor Gate-Läufen ggf.:
  `uv pip install --python .venv/bin/python "pytest>=8" "pytest-asyncio>=0.24" "respx>=0.22"`.
- `tg-/of-b3-governance` braucht den SSH-Remote; im reduzierten Gate-Env
  hängt die Schlüssel-Passphrase am Keychain-Sicherheitskontext. Heute
  16:39 pass, ~17:35 zweimal `remote_unreachable`, 23:0x wieder pass —
  sitzungsabhängig, Inhalt war durchgehend unverändert.
- Der DMG-/Updater-Schritt des Tauri-Builds scheitert ohne
  `TAURI_SIGNING_PRIVATE_KEY`; das Abnahmeartefakt ist das `.app`,
  nicht das DMG. Notiert, nicht gebaut (F1).
- `frontend/src-tauri/target/x86_64-apple-darwin/release.stale-20260809/`
  ist ein beiseite gelegter Build-Baum aus einer widerlegten
  Stale-Link-These (Instrumentenfehler: kurze Rust-Literale sind im
  optimierten Binary als Immediate-Stores nicht byte-suchbar).
  Löschung ist Eigentümerentscheidung.

## §7 Ausdrückliche Bestätigungen

- Kein Live-Lauf einer Löschung; keine Kalendermutation seit dem
  P2-Update `6a1a8e52…` (16:44); kein fremder Termin berührt.
- Kein Merge, kein Tag, kein Release, kein Folgeblock begonnen.
- Keine Lockerung der Eligibility; kein Löschweg ohne frische native
  Probe; Zahlen bleiben als Wahrheitswerte unparsbar (Regressionspin).
- Dialogoptik weiterhin aufgeschoben (F1).
- Pushstatus: `not_performed_owner_action` — Eigentümerbefehl liegt der
  Übergabe bei DEC-068 (spike/calendar-foundation-intel-2026-08-04, „Eigentümergrenzen: abschließende Klassen der Eigentümerhandlungen").

## §8 Verbleibende echte Blocker

1. P3-A Live-Abnahme (Eigentümer, x86_64-Mac, Abend): Vorschau oder
   benannte Stufe samt Rohemission.
2. Live-Record `config/gates/history/b3-live-record.json` entsteht erst
   aus den drei bestätigten Stufen — davor bleiben `platform-live` und
   `module-final` `blocked`.
3. Cleanup-Entscheid „Test Eintrag" nach P3-A (voraussichtlich: bleibt
   stehen, dokumentierte Eigentümerbereinigung).

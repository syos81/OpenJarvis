# B1 Handoff — Kalender sichtbar auf x86_64

Alle Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b1-calendar-visible.*.json`, gebunden als sanitierte
Schnappschüsse unter `config/gates/evidence/b1-calendar-visible/`), aus
Git-Daten, aus dem PII-armen Live-Record und aus den committeten
deklarativen Artefakten.

## §1 Rahmen und Commits

- Worktree mechanisch über `git rev-parse --show-toplevel`; Branch
  `spike/calendar-foundation-intel-2026-08-04`; Ausgangs-Commit
  `7accb1694bd3b51a18c2000fe546c457f048e568` (lokal == remote am Blockstart).
- Funktionscommits, jede Erweiterung maschinenlesbar im Commit-Plan
  begründet (`plan_change`, kein Amend): 1 `e768bab` (Sidebar-Einstieg,
  Navigationstest, B1-Gategerüst), 2 `57e4e5d` (Sidecar-Pfadinjektion in
  den Backend-Start), 3 `08af4d8` (Kalender-UsageDescriptions am Bundle),
  4 `ef3e66c2071e7cea35dea71808dcb016a6d09054` (Bridge-Handshake vor dem
  Statusglauben — der Befund des ersten echten Live-Laufs). Abnahmelauf
  vollständig gegen `ef3e66c…`.

## §2 Phasen (Enum-Werte aus den maschinellen Berichten)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (7 Checks) |
| targeted | `pass` (6 Checks) |
| offline-final | `pass` (9 Checks) |
| platform-live | `pass` (4 Checks, **anwendbar**: echtes Bundle, echter Remote-Stand, produktive Datenbank) |
| module-final | `pass` (4 Checks) |

Kein `fail`, kein `blocked`, kein `pass_with_baseline` im Abschlussstand.

## §3 Sichtbares Ergebnis (Live-Abnahme 2026-08-08)

Reale gepackte Jarvis-App auf dem Intel-Mac, nativ x86_64, aus genau dem
abgenommenen Buildstand: Kalenderberechtigung interaktiv aus der gepackten
App erteilt, ein echter read-only Sync (`completed`, 11/11 Kalender, 63
gesehen, 61 angelegt, 2 aktualisiert, 0 entfernt), 11 Kalender und 61
Termine in der produktiven Datenbank (re-deriviert durch
`pl-b1-live-data`), `/calendar` über den neuen Sidebar-Eintrag erreichbar,
reale Termine im Monatsraster sichtbar, Ansichtsumschaltung intakt —
Sichtbestätigung des Eigentümers. PII-arm: der committete Live-Record
(`config/gates/history/b1-live-record.json`) trägt nur Zähler, Status,
Digeste und Fensterzeiten; sein R4-Leser weist unbekannte Felder ab.

## §4 Bundle, Signatur, Read-only

Mechanisch am Bundle geprüft (`pl-b1-bundle`): App-Binary und beide
Sidecars nativ x86_64; `codesign --verify --strict --deep` gültig; keine
Ad-hoc-Signatur (produktives Zertifikat `de.kluender.jarvis`, Reseal von
innen nach außen); Kalender-Entitlement am verantwortlichen Prozess,
Sidecar mit genau einem Entitlement, keine geerbten Lockerungen;
UsageDescriptions vorhanden; keine EventKit-Schreibselektoren im
eingebetteten Binary (`pl-b1-readonly`). Die Mutationssymbolsperre des
Quellbaus steht unverändert.

## §5 TCC-Zuschreibung (die offene Plattformfrage, mit Beleg)

Das Backend läuft als Kind der App außerhalb des Bündels
(App → uv → .venv-Python → Sidecar). Beleg der Zuschreibung per
Gegenprobe, da TCC-Datenbank und Systemprotokoll ohne Vollzugriff
unlesbar sind: **dasselbe** eingebettete Sidecar-Binary, von
**demselben** .venv-Python außerhalb der App-Kette gestartet, meldet
passiv `NOT_DETERMINED`; innerhalb der App-Kette gilt `full_access`, und
der 63-Termine-Lauf hat gelesen. Die Gewährung folgt also dem
verantwortlichen Prozess der App-Kette — der signierten App — und hängt
weder am Sidecar-Binary noch am Python-Helfer. Festgehalten in
`block_scope.tcc_attribution` des Abnahmerecords.

## §6 K1-Zuordnung (x86_64 belegt / arm64 offen / nicht berührt)

- **K1-O01** — x86_64-Hälfte durch B1 belegt (echter Lesedurchlauf aus der
  gepackten App); arm64-Hälfte offen, Gate bleibt offen.
- **K1-O03** — nicht belegt: jeder Neubau lag vor der Gewährung; eine
  Persistenzbeobachtung nach Rebuild steht aus.
- **K1-O05** — nicht belegt: der reale Bestand enthält 0 Termine mit
  Teilnehmern (mechanisch gezählt).
- **K1-O06** — nicht belegt: der Lese-Paritätsvertrag bindet an
  M2-Referenzhardware.
- **K1-O02** — nicht berührt (arm64).

Kein Gesamtgate wurde auf pass gesetzt.

## §7 Merkmalsprüfung

`of-`/`mf-feature-lineage` gegen den unmittelbaren Vorgänger
(B0g-Merkmalsliste, SHA-256-gebunden): erwartet 271 / zugeordnet 271 /
geändert 0 / fehlend 0; eigene Merkmale B1-001…008: 8/8 nachgewiesen.

## §8 Notierte Nebenbefunde (nach F1 bewusst nicht bearbeitet)

1. Der App-Start (`uv run`) synct das Entwicklungs-venv auf die Lockdatei
   und entfernt Dev-Abhängigkeiten; die Tooling-Suite fiel mittendrin, bis
   `uv sync --extra dev` sie wiederherstellte. Gepackte App und
   Entwicklungsumgebung teilen sich auf diesem Rechner eine Umgebung.
2. `tauri build` meldet einen fehlenden Updater-Signaturschlüssel
   (`TAURI_SIGNING_PRIVATE_KEY`); das App-Bundle selbst entsteht und wird
   produktiv versiegelt. Updater-Signierung liegt außerhalb von B1.
3. Das Bundle trägt mehrere eingebettete Frontend-Asset-Generationen
   (`index-*.js`); geladen wird die aktuelle.
4. `/status` und `/bridge/check` können sich für eine Ansicht
   widersprechen, die nur einen von beiden liest — B1 hat den Workspace
   repariert; andere künftige Konsumenten müssen dieselbe Reihenfolge
   einhalten.

## §9 Ausdrückliche Bestätigungen und Pushstatus

Keine Kalender-Mutation eingeführt, keine Schreib-Parität, keine
arm64- oder Oberflächenparitätsbehauptung, keine Guard-Aktivierung, kein
Merge, kein Tag, kein Release, kein Folgeblock. Die produktive Datenbank
wurde vor dem Live-Lauf byteidentisch gesichert. Rohlogs verbleiben im
gitignorierten Laufzeitbereich. Pushstatus des Branches:
`not_performed_owner_action`.

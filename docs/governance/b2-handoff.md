# B2 Handoff — Monatsansicht in Apple-Parität

Alle Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b2-month-parity.*.json`, gebunden als sanitierte
Schnappschüsse unter `config/gates/evidence/b2-month-parity/`), aus
Git-Daten, aus der eigentümerentschiedenen Vergleichsmatrix und aus den
committeten deklarativen Artefakten.

## §1 Rahmen und Commits

- Branch `spike/calendar-foundation-intel-2026-08-04`; Ausgangs-Commit
  `1e86f436bbf77e1f31ca3806442ebf1ccaa37f50` (B1-Abschluss, lokal == remote).
- Funktionscommits, jede Erweiterung maschinenlesbar im Commit-Plan
  begründet (`plan_change`, kein Amend): 1 `6f3408d` (Angleichung +
  Tagesauswahl + Gerüst), 2 `e292c0c` (Ganztags-Instant-Korrektur,
  WebKit-15-Farben, Zellgrenzen, PaneDivider-Übernahme), 3
  `bcd3b42dbcb719168b611017cf01eb7c37d94762` (Systemakzent-Auswahl,
  Tagesliste, ausblendbare Liste). Abnahmelauf vollständig gegen `bcd3b42…`.

## §2 Phasen (Enum-Werte aus den maschinellen Berichten)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (7 Checks) |
| targeted | `pass` (4 Checks) |
| offline-final | `pass` (9 Checks) |
| platform-live | `pass` (5 Checks, **anwendbar**: Eigentümerabnahme + Regression) |
| module-final | `pass` (5 Checks) |

Kein `fail`, kein `blocked`, kein `pass_with_baseline` im Abschlussstand.

## §3 Vergleichsmatrix (blocklokal, eigentümerentschieden)

`config/gates/history/b2-parity-matrix.json`: **23 Merkmale**, jedes mit
Nachweisart (`automated`/`live_owner`/`both`) und konkretem Nachweis;
kein Merkmal war vorab pass. Eigentümerabnahme 2026-08-09 in drei Runden
neben Apple Kalender, Hell- und Dunkelmodus: **alle 23 pass**, Urteile je
Merkmal in der Matrix. Der R4-Leser erzwingt, dass eine gewollte
Abweichung (`deliberate_deviation`) ihren Grund trägt.

## §4 Tatsächlich verwendete Quellen

- **Wochenbeginn:** `Intl.Locale weekInfo` (Locale-Schicht der Plattform),
  als Parameter des Rasters; Sonntag- und Montag-Konfiguration mechanisch
  getestet. Dieser Mac: `AppleFirstWeekday` ungesetzt, de_DE ⇒ Montag.
  Apples beobachteter Sonntag stammt aus dessen app-privater Einstellung —
  dokumentierte Quellenlage, keine Systemabweichung von Jarvis.
- **Theme/Farben:** bestehende Jarvis-Theme-Tokens (Flächen, Text, Linien,
  semantisches Rot für „heute") plus die semantischen CSS-Systemfarben
  `Highlight`/`HighlightText` für Auswahl und aktiven Umschalter — keine
  eigenen Farbwerte. `color-mix()` ist per Wächtertest aus den
  Kalender-Tokens verbannt: die WKWebView dieses Macs (WebKit 17613)
  löst es nicht auf; genau daran waren Auswahl und Rasterlinien im ersten
  Livelauf unsichtbar.

## §5 Korrektheitskorrektur aus der Live-Abnahme

Alle Ganztagstermine erschienen einen Tag zu früh. Mechanisch belegt:
die produktive Datenbank speichert Ganztagstermine als rohe
Mitternachts-Instants (`…T22:00:00Z`), der Leser schnitt sie als
normalisierte Datums-Strings. **Altfehler aus der Modulerstellung** —
`termintage` war seit dem B1-Abschluss byteidentisch (git-belegt), keine
B2-Wochenbeginn-Regression. Korrigiert mit zuerst geschriebenem,
fallendem Test in Realform samt Gegentest (kein Tag zu viel bei
mehrtägigen Terminen); die Altfixtures des falschen Vertrags wurden auf
die belegte Realform berichtigt.

## §6 Bewusste Abweichungen und F1-Reste

- **Tagesliste rechts** (Tagesklick listet die Termine des Tages): als
  `deliberate_deviation` in der Matrix deklariert — Apples Monatsansicht
  hat keinen rechten Bereich; Eigentümerentscheid, keine Parität.
- **Kalenderliste** bleibt eine Seitenleiste innerhalb der Kalenderfläche
  (nicht die globale App-Sidebar) — F1-Rest, eigentümerabgenommen.
- Keine Parität behauptet für Tag/Woche/Jahr, keine Pixelgleichheit,
  kein arm64.

## §7 Merkmalsprüfung und B1-Regression

`of-`/`mf-feature-lineage` gegen den B1-Vorgänger: erwartet 281 /
zugeordnet 281 / geändert 0 / fehlend 0; eigene Merkmale B2-001…010:
10/10. B1-Funktion live regressionsfrei: gepackte x86_64-App startet,
Bundle streng signaturverifiziert, produktive Datenbank weiterhin mit
echten Kalendern, Terminen und Syncläufen (`pl-b2-regression`), Read-only
ohne Schreibselektoren (`pl-b1-readonly`).

## §8 Notierte Befunde (nach F1 nicht gebaut)

1. **Farbsprachen-Ausrollung:** die Kalender-Farbsprache (semantische
   Systemfarben) auf das übrige Jarvis ausrollen — eigener Block, der
   Kalender ist die Referenz. Dorthin gehört auch: **Zeigerwechsel bei
   Hover** über klickbaren Elementen, wie ihn das Kontaktmodul schon hat —
   dieselben Bedienelemente werden dort ohnehin angefasst.
2. **Ausblendbare Bereiche im Kontaktmodul** existieren nicht (nur die
   Kalenderliste kann es jetzt); bei Bedarf eigener kleiner Block.
3. **venv-Resync durch den App-Start** (`uv run` entfernt
   Dev-Abhängigkeiten): traf diesen Block nach jeder Eigentümerrunde;
   jeweils mit `uv sync --extra dev` wiederhergestellt. Stehender Befund
   aus B1.
4. Ganztags-Instants tragen keinen Zonenanker; eine von der
   Erstellungszone abweichende Anzeigezone würde sie verschieben (im
   B2-Umfang identisch; als Grenze im Rastertest dokumentiert).

## §9 Ausdrückliche Bestätigungen und Pushstatus

Keine Kalender-Mutation, keine Schreib-Parität, kein Auto-Sync, keine
Guard-Aktivierung, kein Merge, kein Tag, kein Release, kein Folgeblock.
Rohlogs verbleiben im gitignorierten Laufzeitbereich; die Matrix trägt
keine realen Termininhalte. Pushstatus des Branches:
`not_performed_owner_action`.

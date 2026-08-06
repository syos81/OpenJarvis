---
Status: normativ (B0b Abschluss-Handoff)
Erzeugt aus: maschinelle Gate-Ergebnisse, sanitierte Evidenz, Git-Daten, deklarative Manifeste, reale Eigentümer- und Rechteprüfungen
Zielbranch: spike/calendar-foundation-intel-2026-08-04
Ersetzt: die B0a-4-Fassung dieses Handoffs (historisch über `a1adabf` unverändert nachvollziehbar)
---

# B0b-Handoff — Zustand nach der offline durchgeführten K1-Arbeit

**Kalender K1 ist nicht abgeschlossen.** Diese Aussage steht bewusst vor
allem anderen. Die Zahlen in §3 stammen ausschließlich aus dem Gate-Lauf
`mf-k1-status`; kein Wert in diesem Dokument ist vorhergesagt.

## §1 Git-Zustand

| Größe | Wert |
|---|---|
| Kalenderbranch | `spike/calendar-foundation-intel-2026-08-04` |
| Ausgangscommit B0b | `a1adabf20884b7c350a439a0e8023e4b38f2b910` |
| Commit 1 | `57dafef` — PII-Redaktion angeglichen, Guard-Vertrauensmodell |
| Commit 2 | `8d2a568` — K1 offline, Gates O04 und O09 |
| Commit 3 | `29fc013` — abgeleitete K1-Definition, Paritätskorrektur, Regel R3 |
| Commit 4 | der Commit, der diese Datei trägt — Evidenz und Handoff |
| Remote-Stand vor Eigentümer-Push | `a1adabf` |
| Amends innerhalb B0b | keine |
| Rebase, Squash, Cherry-pick | keine |
| Pushstatus | `not_performed_owner_action` |

Der Commitplan wurde von drei auf vier Commits geändert. Das war eine
Eigentümerentscheidung, nicht eine nachträgliche Schönung; sie steht in
`config/gates/history/b0b-commit-plan.json` unter `plan_change`.

## §2 Guard

| Größe | Wert |
|---|---|
| Guard-Basis | `d037cb67502ab7fdcef95161bdbf2857181d0354`, mechanisch abgeleitet, genau eine Merge-Base |
| Aktive Guard-Version | `1.1.0` |
| Quellcommit | `57dafef116a64571394ea3d32f6cd049a960cd6f` |
| Aktiver Paket-Hash | `fe89c98b37cbf471e425b2123a05ce34378017590f77690edc7c76c9c1bd50c7` |
| Hook-Registrierung | `/Library/Application Support/ClaudeCode/managed-settings.json`, `root:wheel` |
| Externer Guard-Pfad | `/usr/local/jarvis-guard`, `root:wheel` |
| Interpreter | Command-Line-Tools-Python 3.9.6, Ahnenkette lückenlos `root:wheel` bis `/` |
| Eigentümeraktivierung | durch Lukas, mit Kennworteingabe |

Der Hash wurde nicht abgelesen, sondern aus dem installierten Paket neu
berechnet und mit der geschützten Aktivierungsevidenz verglichen.

### §2.1 Vertrauensmodell

Verbindlich und maschinenlesbar in `config/governance/guard-trust-model.json`;
`CLAUDE.md` verwendet dieselbe Semantik; das Gate `claim-lint` weist stärkere
Behauptungen zurück.

- Der Guard ist ein **Disziplinmechanismus**. Er ist **keine** vollständige
  Sicherheitsgrenze gegen einen feindlichen Akteur mit Lukas'
  Benutzerrechten.
- Die Claude-Code-Anwendung ist benutzerschreibbar und bleibt eine **nicht
  schließbare Vertrauenswurzel**.
- Die Grenze lautet `requires_interactive_owner_authentication`, nicht
  `technically_impossible`.
- Das Schutzprotokoll ist von der Sitzung weder kürzbar noch löschbar, aber
  **nach vorn anhängbar und damit fälschbar**. Es war in diesem Block nie
  alleiniger Nachweis; jede Aussage stützt sich zusätzlich auf
  reproduzierbare aktive Tests, Hashbindung und Dateirechte.

## §3 K1 — Stand aus dem Gate-Lauf

Die Stufe ist abgeleitet, nicht erfunden: K1 ist genau die vorhandene
maschinenlesbare Gate-Menge abzüglich der herausgenommenen Schreib-Parität,
je Gate zusätzlich mit `offline` oder `live` ausgezeichnet. Der Stufenname
ist per SHA-256 an genau diese Gate-Menge gebunden
(`config/gates/k1/calendar-k1-definition.json`).

Die Verteilung steht in der vom Lauf erzeugten Abschlussmatrix
`.gate-runtime/k1/calendar-k1-closing-matrix.json` und wird von
`of-k1-status` und `mf-k1-status` berichtet. Sie wird hier nicht wiederholt,
damit es nur eine Quelle gibt.

### §3.1 Offline abgeschlossener Umfang, gateweise

Erfüllt sind ausschließlich Gates der Ausführungsklasse `offline` mit
auflösbarer Evidenzreferenz:

- `K1-F01` Python-Testlauf `tests/personal` — jetzt ohne roten Test
- `K1-F02` Kalender-Suite
- `K1-F03` Frontend `vitest run`
- `K1-F04` `tsc --noEmit`
- `K1-F05` `ruff` auf neuem Code
- `K1-F06` Sidecar-Bau, **keine Schreibselektoren im Binary**
- `K1-F07` kalenderfreier Handshake gegen das echte Binary
- `K1-F08` fail-closed ohne Berechtigung
- `K1-O04` große Bestände — offline gemessen
- `K1-O09` vorbestehend roter Test — behoben

### §3.2 Offen, mit Ausführungsklasse

- `K1-O01` Lesedurchlauf aus der gepackten App, beide Architekturen — `live`
  (TCC, gepackte App, arm64-Hardware)
- `K1-O02` ARM64 vollständig — `live` (arm64-Hardware)
- `K1-O03` TCC-Persistenzmatrix — `live` (TCC, gepackte App)
- `K1-O05` Teilnehmer im Echtbetrieb — `live` (Echtbetrieb)
- `K1-O06` Apple-Paritätsvertrag, **Lese-Parität** — `live` (Echtbetrieb,
  M2-Referenzhardware)
- `K1-O08` zweiter Datenpfad `gcalendar.py` — `offline`, aber blockiert:
  Baseline §5 Schritt 2 verweist auf „Register 20 §5"; ein Dokument dieser
  Nummer existiert nicht, die Reihe endet bei 19. Schritt 4 verlangt einen
  Eintrag im Entscheidungsregister. Beides sind Eigentümerhandlungen.

### §3.3 Aus K1 herausgenommen

Die **Schreib-Parität** — P-6, P-7, P-9 und der schreibende Anteil von P-11 —
sowie das Gate `Schreiben` sind aus K1 herausgenommen und werden als eigene,
spätere Architekturentscheidung geführt. Sie zählen **weder als erfüllt noch
als offen**.

Grund: die Gate-Liste war fehlerhaft, nicht die Umsetzung. „Keine
EventKit-Schreibselektoren im gebauten Binary" ist eine positive
K1-Invariante; die Schreib-Parität hätte sie zwingend verletzt. Der Konflikt
ist in `config/gates/k1/calendar-k1-definition.json` dokumentiert und wird
nicht als offenes Gate weitergeführt.

**Keine DEC-Nummer wurde vergeben.** Es steht ein dauerhafter, markierter
Platzhalter `{{DEC_ID_CALENDAR_WRITE_PARITY}}`. Mechanischer Befund: über
alle Markdown-Dokumente beider Linien sind `DEC-001` bis `DEC-055` und
`DEC-D01` bis `DEC-D17` lückenlos belegt, `DEC-056` und `DEC-D18` sind
unbelegt. Vergeben wurde trotzdem nichts — die Vergabe ist Eigentümerhandlung,
und die kanonische Linie `jarvis/rebuild-v1` steht eingefroren auf `c222601`,
ist aber **nicht integriert**; Freiheit gegen ihre künftige Belegung ist
damit nicht gezeigt. Genau diese Kollisionsklasse musste B0a-3 auflösen.

## §4 Ausdrücklich nicht abgenommen

- keine produktive Kalenderfreigabe,
- keine vollständige Plattformabnahme,
- keine M2-Pro-Live-Abnahme,
- keine signierte Universal-Releasefähigkeit,
- kein Abschluss des Kalenderfachmoduls,
- keine Kontakte-M2-Abnahme.

Die plattformabhängigen K1-Gates sind als **offene K1-Gates** geführt und
nicht als `not_applicable`-Phasenerklärung getarnt. Die Phase
`platform-live` von B0b deckt ausschließlich die Live-Regression des aktiven
Guards ab.

## §5 Historische Abnahme und aktuelle Erhaltung

Historisch abgenommen und hashvalide: **B0a-1, B0a-2, B0a-3, B0a-4**. Die
Manifeste werden nicht gegen den heutigen HEAD erneut ausgeführt.

Die B0a-4-Aussage „PII-Scrubbing mit dokumentierter Lücke bei abgeflachten
Pfaden" bleibt als historische Aussage unverändert. Geschlossen wurde die
Lücke auf der **aktuellen Linie**, nicht rückwirkend.

Aktuelle Erhaltung: **111 von 111** Vorgängermerkmale
(24 + 38 + 14 + 35), geprüft von `of-preservation` und `mf-preservation`.

Die Evidenz aller vier historischen Abnahmen liegt seit B0b als committeter,
PII-geprüfter Schnappschuss unter `config/gates/evidence/`. Vorher war sie an
den gitignorierten Laufzeitbereich gebunden — eine Bindung, die brach, sobald
derselbe Block erneut lief.

## §6 Offene Befunde nach B0b

1. **Claude-Code-Anwendung als offene Vertrauenswurzel** — unverändert, durch
   keinen Bestandteil dieses Blocks schließbar.
2. **Administratorkonto** — mit Kennwort ist jede Grenze aufhebbar; die
   Grenze ist Authentisierung, nicht Unmöglichkeit.
3. **Schutzprotokoll nach vorn fälschbar** — unverändert.
4. **Backstop-Ebene überschätzt bewusst** — der Rohtextvergleich schlägt auch
   an, wenn ein Dokument einen verbotenen Befehl nur erwähnt. Sichere
   Richtung; eine Entschärfung wäre eine Verringerung der Verstoßmenge.
5. **Mehrdeutige Git-Operationen ungesperrt** — Matrix in
   `config/guard/history-rewrite-matrix.json`.
6. **`Register 20 §5` existiert nicht.** Die Kalender-Baseline §5 stützt den
   Ablöseplan für `gcalendar.py` auf ein Dokument, das es nicht gibt.
   Blockiert `K1-O08`.
7. **Abnahmeprofile A/B/C und Overlays P/S/H existieren nicht.** Sie waren
   Prompt-Prosa, wurden in B0b **nicht angewendet** und erzeugen keinen
   Abnahmenachweis. Ein Gate prüft, dass sie in keinem K1-Dokument als
   Klassifikation auftauchen. Einführung als maschinenlesbares
   Governance-Artefakt ist einem eigenen Block vor dem nächsten Modulauftrag
   vorbehalten.
8. **Schreib-Parität ohne Entscheidungsnummer** — siehe §3.3.

## §7 Nächste zulässige Arbeitsblöcke

Verbindlich ist `config/governance/delivery-order.json`. Sie führt:
Lieferposition 1 Kontakte, 2 Kalender, 3 Ambient Interaction V1,
4 Trading Intelligence T1.

Aus dem Zustand nach B0b folgen als zulässige nächste Blöcke:

- die **Live-Abnahme der offenen K1-Gates** auf echter Hardware beider
  Architekturen (`K1-O01`, `K1-O02`, `K1-O03`, `K1-O05`, `K1-O06`),
- die **Eigentümerklärung zu `Register 20 §5`** und der Ablöseplan für
  `gcalendar.py` (`K1-O08`),
- die **Architekturentscheidung zur Schreib-Parität** samt Nummernvergabe,
- der **Governance-Block für Abnahmeprofile und Overlays**.

Zwischen **Ambient-P0** und **Kontakte M2** wird hier **keine** Vorentscheidung
getroffen. Die Lieferreihenfolge ordnet die Elemente; welcher der beiden
Aufträge zuerst gefahren wird, ist nicht Gegenstand dieses Blocks und wird
hier nicht vorweggenommen.

## §8 Was B0b nicht getan hat

Keine fachliche Entscheidung, keine neue Baseline zur Umgehung offener
Arbeit, keine neue DEC- oder ADR-Datei, keine Nummernvergabe, keine Änderung
am Bundle-Identifier, keine Kontakte-Arbeit, kein Ambient-P0, keine
Kalenderstufe nach K1, kein Tag, kein Release, kein Push.

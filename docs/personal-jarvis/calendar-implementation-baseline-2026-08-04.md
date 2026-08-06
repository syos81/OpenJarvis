---
Status: normativ (Modul-2-Implementierungsbaseline; ändert keine Regel der Architektur-Baseline v3)
Zugehörige ADRs: ADR-0002, ADR-0012, ADR-0016 (Sidecar-Analogie), ADR-0018; Mutationslinie ADR-0025/ADR-0026 (§6, Umnummerierung vollzogen)
Zugehörige DEC-Einträge: DEC-030, DEC-042, DEC-045 (rebuild-v1: Modulreihenfolge), DEC-055 (Kalender-Fundament-Spike), DEC-050 (rebuild-v1: acht Kontakte-Gates)
Evidenz: [calendar-read-probe-x86_64-2026-08-04](../testing/calendar-read-probe-x86_64-2026-08-04.md) · [calendar-foundation-spike-2026-08-04](calendar-foundation-spike-2026-08-04.md) · Read-only-Altcode-Audit des alten Jarvis-Kalenders (Chat, 2026-08-04)
---

# Kalender Modul 2 — Implementierungsbaseline (2026-08-04)

## §1 Zweck und Geltung

Dieses Dokument friert **vor** dem ersten Produktcode die verbindlichen
Entscheidungen, die Altcode-Übernahme, den Apple-Paritätsvertrag, den
ADR-Kollisionsplan und die Implementierungsbasis für **Modul 2 Kalender** ein.

Es **startet das Modul nicht**. Die Modulreihenfolge (16 §4, DEC-045 der Linie `jarvis/rebuild-v1`) und die
acht Kontakte-Gates (DEC-050 der Linie `jarvis/rebuild-v1`) bleiben unberührt: Kontakte ist auf Intel fertig
und eingefroren (`1f03bfa`), die M2-arm64-Abnahme steht aus. Kalenderarbeit
auf Intel ist erlaubt; ein finaler Merge, ein Tag, ein Release oder ein
behaupteter Modulabschluss sind es nicht.

**Verifizierter Ausgangszustand (2026-08-04, read-only geprüft):**

| Referenz | Stand |
|---|---|
| Kalender-Spike | `spike/calendar-foundation-intel-2026-08-04` @ `f6f973a`, Worktree sauber, identisch mit `origin` |
| Kontakte-Freeze | `1f03bfa` („docs(contacts): freeze intel scope") — **Vorfahre** des Kalender-Spikes |
| Architekturstand | `jarvis/rebuild-v1` @ `c222601` — **kein** Vorfahre des Spikes |
| Merge-Base Spike ↔ rebuild-v1 | `d037cb6` (2026-07-29); rebuild-v1 liegt genau **einen** Docs-Commit (`c222601`) voraus, die Spike-/Kontakte-Linie 33 Commits |

## §2 Verbindliche Entscheidungen (B-1 … B-15)

- **B-1 Kanonische Quelle.** Apple Kalender/EventKit ist die kanonische
  Providerquelle des Moduls. `personal/jarvis.db` bleibt die **einzige**
  fachliche lokale Wahrheit (AV-16, 06).
- **B-2 Projektion ohne Rückweg.** Such-/Knowledge-Daten sind ausschließlich
  erneuerbare Projektion aus der kanonischen DB (vollständiger Rebuild
  jederzeit möglich). **Kein Rückschreiben** aus einem Index — weder in die
  kanonische DB noch zu EventKit.
- **B-3 Voller Modulumfang.** Der Kalender wird **vollständig** umgesetzt:
  Read/Sync, Create, Update, Delete, Freigaben, Audit, At-most-once,
  Recovery und Read-back. Kein Feld und keine Operation wird stillschweigend
  gestrichen; Streichungen sind Eigentümerentscheidungen.
- **B-4 Kein vorgezogener Abschluss.** Ein interner erster Leseblock ist
  **kein** Read-only-Modulabschluss. Er wird nicht veröffentlicht, nicht
  getaggt und nicht eingefroren (Verbot einer nur lesenden Vorstufe, AV-3).
- **B-5 Referenz und Zielplattformen.** Apple Kalender auf dem M2 ist die
  visuelle und funktionale Hauptreferenz. Intel macOS 12.7.6 ist
  **gleichwertiges** Produktziel (ADR-0018) — kein Kompatibilitätstest.
- **B-6 Bewusste Abweichungen.** Jarvis-Freigabe (Approval vor jeder
  Provider-Mutation) und Audit sind die **einzigen** bewusst sichtbaren
  Abweichungen vom Apple-Ablauf. Alles andere strebt Parität an (§4).
- **B-7 Zeitzonen.** Die Standardanzeige nutzt die **Systemzeitzone**.
  `event.timeZone` und schwebende Termine (Zeitzone NULL) bleiben fachlich
  erhalten und werden nie nach UTC „normalisiert". `Europe/Berlin` darf
  **nirgends** hart kodiert werden.
- **B-8 Fenstermodell.** Das initiale Ladefenster **−90/+365 Tage** ist
  Startcache, keine dauerhafte Produktgrenze. Navigation darf das Fenster
  kontrolliert erweitern; jeder Lauf nennt sein Fenster. **Löschungen werden
  ausschließlich innerhalb eines vollständig beobachteten Fensters
  abgeleitet** (drei Tombstone-Bedingungen des Fundament-Spikes §8.5;
  Fensterwechsel ist ein eigener Vorgang ohne Löschableitung).
- **B-9 Reminders.** Erinnerungen (`EKReminder`) bleiben ein **eigenes,
  späteres Modul** (16 §1). Kein Reminders-Code in Modul 2.
- **B-10 Ein Datenpfad.** `gcalendar.py` bleibt **kein** zweiter Datenpfad
  (Register 20 §2, C-11 REPLACE). Ablöseplan in §5; **jetzt wird nichts
  gelöscht**.
- **B-11 Zuordnungen.** Workspace-Zuordnungen von Kalendern sind getrennte
  **lokale Entscheidungen**: nie aus Kalendertiteln, Farben oder Arten
  geraten, nie zu EventKit zurückgeschrieben, nie von einem Sync
  überschrieben (Beobachtung ↔ Entscheidung, §3).
- **B-12 Berechtigungs-APIs.** macOS 12.7.6 nutzt den Legacy-Zugriffspfad
  (`requestAccess(to:)`, klassische Statuswerte). macOS 14+ nutzt
  `fullAccess`/`writeOnly` (`requestFullAccessToEvents`) über `#available`
  bzw. einen nachweislich auf beiden SDK-Ständen kompilierenden gemeinsamen
  Quelltext. Der Altcode-Befund „`@unknown default` ⇒ `unknown` ⇒
  `permission_denied` trotz erteiltem Vollzugriff" darf im neuen Code
  strukturell nicht mehr auftreten.
- **B-13 Usage-Descriptions.** Beide benötigten Schlüssel werden geführt:
  `NSCalendarsUsageDescription` (macOS ≤ 13) **und**
  `NSCalendarsFullAccessUsageDescription` (macOS 14+). Zusätzlich trägt der
  Elternprozess das Entitlement
  `com.apple.security.personal-information.calendars` — ohne dieses gibt es
  unter Hardened Runtime keine Nachfrage, sondern eine stille Ablehnung
  (belegt in der Leseprobe).
- **B-14 TCC-Beleg statt Annahme.** Die TCC-Verantwortung von App und
  Sidecar wird **je Architektur im verpackten Produkt** belegt (Liveläufe,
  Persistenzmatrix), nicht aus der Intel-Probe extrapoliert. Der Befund
  „unsigniertes Kind erbt den Zugriff" ist ein Intel-Befund und gilt nicht
  für arm64.
- **B-15 Dual-Architektur.** Gemeinsamer Quellcode, getrennte **signierte**
  x86_64- und arm64-Artefakte, echte Liveläufe auf beiden Macs (ADR-0018,
  15 §7). Ein Ergebnis der einen Architektur gilt nie für die andere.

## §3 Altcode-Übernahme (verbindlich)

Quelle: Read-only-Audit des alten Jarvis (`/Users/lukasklunder/Jarvis`,
HEAD `51c6d27`, 69 Kalenderdateien). Übernommen werden **Verträge, reine
Funktionen und Regeln** — kein lauffähiger Alt-Code als Ganzes.

**Übernehmen / anpassen:**

| Nr. | Komponente | Urteil | Auflage |
|---|---|---|---|
| A-1 | `frontend/src/lib/contracts/calendar-grid.ts` samt 42 Tests | **ADAPT** | Zeitzone parametrisieren (B-7), Jahresansicht ergänzen; DST-Regeln (nicht existente/mehrdeutige Lokalzeit **ablehnen statt raten**) unverändert erhalten |
| A-2 | `parseEventDate` (zoned ISO → fraktionale Sekunden → Wall-Clock) | **ADAPT** | inklusive der 44D.3-Korrektur; Sprache je Zielschicht |
| A-3 | Kalenderinventar-Leselogik (`listCalendarsFromEventKit`, Inventar-DTO) | **ADAPT** | + `isImmutable`, `allowedEntityTypes`; Quelle nur maskiert nach außen |
| A-4 | EventKit-Ereignislesung (`predicateForEvents`, deterministische Sortierung/Paginierung) | **ADAPT** | Feldumfang v1 des Fundament-Spikes §10; `time_zone` nullable |
| A-5 | Strikte Request-/Response-Validierung (schemaVersion, gespiegelte requestId, **exakte** Feldmengen, Unbekanntes fail-closed) | **ADAPT** | auf JSON-Lines-Protokoll mit Handshake/`caps`/Shutdown (Kontakte-Muster) |
| A-6 | Gate-Reihenfolge: Payload-Validierung → Berechtigungs-Gate → Allowlist-Gate → **höchstens ein** Provider-Aufruf, kein Retry | **ADAPT** | als Vertragstext; Ausführung läuft über den Mutation Core der Kontakte (ADR-0025/0026-Mutationslinie) |
| A-7 | Geschlossene Fehlerklassifikation (native kinds → geschlossenes Outcome; nie Rohfehler, nie Pfade, nie Inhalte) | **ADAPT** | `outcome_unknown` ist eigener Terminalzustand und führt nur in den Abgleich |
| A-8 | UI-Zustands- und Ehrlichkeitsregeln | **ADAPT** | geladen-und-leer ≠ ungeladen; `ok:true` beweist keinen Erfolg; Sync-Ergebnis ist Historie, nie Zustand; Sichtbarkeitsfilter sind reine Anzeige; differenzierter Leer-/Berechtigungszustand; eine Gesamtaussage je Sync |
| A-9 | Trennung beobachtete Providerdaten ↔ lokale Entscheidungen (`upsertSeen` mit vier Ausgängen, Deaktivierung statt Löschung, Zuordnung in eigener Tabelle) | **ADAPT** | auf das kanonische Schema des Fundament-Spikes §7 |

**Nicht übernehmen:**

| Nr. | Komponente | Grund |
|---|---|---|
| R-1 | Alte Next.js-Routen (`app/api/core/connectors/calendar/apple/**`) | fremde Laufzeitumgebung |
| R-2 | `connector_calendar_events` als Schema | strukturell datenminimiert gegen den Modul-Scope (keine Teilnehmer/Serien/Alarme/URLs) |
| R-3 | `better-sqlite3`/`core-db`-Anbindung | Persistenz läuft über `personal/jarvis.db` + Migrations-Ledger |
| R-4 | FS-Execution-Claim (`apple-calendar-execution-service`) | abgelöst durch Outbox-Claim + verbrauchte Freigabe + Einmalwächter der Mutationslinie |
| R-5 | Ad-hoc-Signierung (`codesign --sign -`, build-clt.sh) | ersetzt durch zertifikatsgebundene DR + Hardened Runtime + Entitlement |
| R-6 | Env-Pfadkonfiguration (`APPLE_CALENDAR_BRIDGE_BINARY_PATH` u. a.) | Sidecar-Pfad kommt aus dem Bundle |
| R-7 | Reminders-Code der alten Bridge | B-9 |
| R-8 | Mock-/Legacy-Datenpfade (`mock-calendar.ts`, `calendar-read-model.ts`) | tot |
| R-9 | Brain-/Voice-/Turn-Integration | nicht in Kalender v1 |

Die alte Board-UI (`AppleCalendarBoard.tsx`) ist **nur Vorlage** für Layout
und Zustandsmenge. Sie belegt **keine** Apple-Parität (§4).

## §4 Apple-Paritätsvertrag (prüfbare Abnahmekriterien P-1 … P-15)

Referenz ist Apple Kalender auf dem M2 (B-5). Jedes Kriterium wird am Ende
**visuell und funktional gegen die M2-Referenz** verglichen; bis dahin wird
keine 1:1-Parität behauptet. Freigabe + Audit sind die einzigen zugelassenen
sichtbaren Zusatzschritte (B-6).

- **P-1 Seitenleiste und Kalendergruppen.** Kalender gruppiert nach Quelle
  (wie Apple: z. B. iCloud / Abonnements / Andere), je Kalender Farbe,
  Name, Checkbox zum Ein-/Ausblenden. Ausblenden ist reine Anzeige und wird
  nie als Zuordnung gespeichert. *Prüfung:* Screenshot-Vergleich Struktur +
  Test „Ausblenden ändert keine Persistenz".
- **P-2 Ansichten.** Monat, Woche, Tag **und Jahr** vorhanden; Umschalter
  und Tastaturäquivalente wie Apple; ‹/›/„Heute"-Navigation in jeder
  Ansicht. *Prüfung:* je Ansicht ein Referenzvergleich mit identischem
  Datenbestand.
- **P-3 Zeitachsen und Ganztagsbereiche.** Woche/Tag mit Stundenraster,
  Termine nach Uhrzeit positioniert und in der Höhe proportional zur Dauer;
  eigener Ganztagsbereich oberhalb der Zeitachse; Jetzt-Linie am heutigen
  Tag. *Prüfung:* Positions-/Überlappungstest mit deterministischem Fixture.
- **P-4 Suche.** Volltextsuche über Titel, Ort, Notizen, Teilnehmer mit
  Trefferliste und Sprung zum Termin. *Prüfung:* Suchtest gegen Fixture;
  Treffer außerhalb des geladenen Fensters erweitern das Fenster
  kontrolliert (B-8) oder werden als „außerhalb" ausgewiesen — nie still
  verschluckt.
- **P-5 Ereignisdetails.** Klick öffnet Detail-Popover/-bereich mit Titel,
  Kalender, Zeit (inkl. Zeitzone, falls gesetzt), Ort, URL, Notizen,
  Alarmen, Teilnehmern samt Antwortstatus, Serienangabe. *Prüfung:*
  Feldvollständigkeit gegen den v1-Lesevertrag.
- **P-6 Create/Update/Delete aus dem Kalender.** Direkt aus der Ansicht
  vorbereitbar (Doppelklick in Slot = neuer Termin; Bearbeiten/Löschen am
  Termin). Ausführung **immer** erst nach Freigabe (B-6); nicht schreibbare
  Kalender bieten die Fläche gar nicht erst an. *Prüfung:* je Operation ein
  Ende-zu-Ende-Test Vorbereitung → Freigabe → genau ein Provider-Aufruf →
  Read-back.
- **P-7 Drag-and-drop und Größenänderung.** Verschieben (Zeit/Tag) und
  Dauer ziehen wie Apple; das Loslassen erzeugt eine **Freigabeanfrage mit
  Vorschau** (vorher → nachher), nie eine Direktmutation. Abbruch stellt
  die Ansicht unverändert wieder her. *Prüfung:* Interaktionstest + Beleg,
  dass ohne Freigabe kein Provider-Aufruf stattfand.
- **P-8 Mehrtägige und wiederkehrende Ereignisse.** Mehrtägige als
  durchgehender Balken über Tagesgrenzen; Serien mit Wiederholungssymbol;
  Instanzen aus der **rohen** Regel abgeleitet (Cache, nie Wahrheit).
  *Prüfung:* Fixture mit Serien inkl. Ausnahmen; Rendering-Vergleich.
- **P-9 Einzel- vs. Serienbearbeitung.** Bearbeiten/Löschen einer
  Serieninstanz fragt wie Apple: „Nur dieser Termin" / „Alle zukünftigen" /
  („Alle"). Die Wahl wird in der Freigabevorschau ausgewiesen und exakt so
  ausgeführt. *Prüfung:* je Span-Variante ein Ende-zu-Ende-Test mit
  Read-back der Nachbarinstanzen (unberührt bleibt unberührt).
- **P-10 Zeitzonen und schwebende Termine.** Anzeige in Systemzeitzone
  (B-7); Termine mit abweichender `event.timeZone` zeigen sie im Detail;
  schwebende Termine bleiben schwebend (kein UTC-Anker). *Prüfung:*
  Fixture mit gemischten Zonen + Simulation eines
  Systemzeitzonen-Wechsels: ganztägige/schwebende Termine verschieben sich
  nicht.
- **P-11 Feldumfang.** Ort, URL, Notizen, Alarme, Teilnehmer und
  Antwortstatus werden gelesen, angezeigt und (soweit der Provider es
  erlaubt) geschrieben. *Prüfung:* Feldmatrix v1 mit Read-back je Feld.
- **P-12 Kontextmenüs und Tastatur.** Rechtsklick am Termin/Slot mit den
  Apple-üblichen Aktionen; Pfeilnavigation, Enter (Details), Cmd-Klick-
  Äquivalente, Escape schließt. *Prüfung:* Bedienbarkeitstest ohne Maus
  für die Kernpfade Ansehen/Vorbereiten.
- **P-13 Hell-/Dunkelmodus und Barrierefreiheit.** Beide Modi ohne hart
  kodierte Farben außerhalb der Token; Raster mit korrekten Rollen/Labels,
  sichtbarer Fokus, Termindarstellung nicht nur über Farbe unterscheidbar.
  *Prüfung:* Moduswechsel-Screenshots + Accessibility-Audit der
  Kernflächen.
- **P-14 Externe Änderungen.** In Apple Kalender vorgenommene Änderungen
  erscheinen ohne App-Neustart: `EKEventStoreChangedNotification` ist
  **Auslöser** eines kontrollierten Fenster-Diffs, nie ein Delta.
  *Prüfung:* Livetest „extern ändern → Jarvis zeigt es", plus Beleg, dass
  eigene Schreibvorgänge nicht als Fremdänderung doppeln (Digest).
- **P-15 Zustände.** Lade-, Leer-, Berechtigungs- (not_determined /
  denied / restricted / eingeschränkt), Stale-, Partial- und
  Fehlerzustände sind unterscheidbar, benennen den Grund und den nächsten
  Schritt; ein unvollständig gelesenes Fenster wird als unvollständig
  ausgewiesen. *Prüfung:* je Zustand ein erzwungener Testpfad.

## §5 Ablöseplan `gcalendar.py` (kontrolliert, nichts wird jetzt gelöscht)

Betroffen: `src/openjarvis/connectors/gcalendar.py` (zweiter Datenpfad in
den Upstream-Index) und seine Verbraucher
`src/openjarvis/skills/data/calendar-prep.toml`,
`src/openjarvis/agents/morning_digest.py`,
`src/openjarvis/tools/digest_collect.py`.

1. **Sofort (mit Modulstart):** `gcalendar` wird als stillzulegender
   Altpfad markiert und in keiner neuen Konfiguration aktiviert. Kein
   Löschen, keine Codeänderung vor dem Modulstart.
2. **Mit dem ersten Leseblock:** Die kanonische Kalenderwahrheit entsteht in
   `personal/jarvis.db`; die kontrollierte Suchprojektion (Z-1, Register 20
   §5) wird für Kalenderdaten definiert. `gcalendar` darf ab da keine neuen
   Einträge in den Index schreiben (deaktiviert, nicht entfernt).
3. **Verbraucher-Umstellung:** `calendar-prep.toml`, `morning_digest.py`
   und `digest_collect.py` beziehen Kalenderdaten ausschließlich über die
   kontrollierte Projektion bzw. die Read-API des Moduls. Bis dahin gelten
   sie als Altverbraucher ohne Zusage.
4. **Entfernung:** `gcalendar.py` wird erst entfernt, wenn (a) die
   Verbraucher umgestellt sind, (b) der Index für Kalender vollständig aus
   der Projektion rebuildbar ist und (c) die Entscheidung im
   Entscheidungsregister festgehalten wurde. Google bleibt als späterer
   API-/CalDAV-Adapter des Moduls möglich (C-11: Referenz, nie Vorstufe).

## §6 Entscheidungskollisionen — Befund und vollzogene Auflösung

**Dieser Paragraph ist die einzige normative Stelle** für Linien, Merge-Base,
Kollisionsbefund und Umnummerierungs-Mapping. Die maschinenlesbare Projektion
liegt in `config/governance/decision-collisions.json` und wird vom Gate
`of-single-normative-source` gegen diesen Text geprüft; sie ist Abbild, nicht
zweite Wahrheit. Der frühere Nachtrag
`docs/governance/b0a-2-decision-collisions.md` ist seit der Integration
ausdrücklich **historisch und nicht normativ**.

### §6.1 Linien und Merge-Base

| Rolle | Referenz | Belegter Stand |
|---|---|---|
| kanonische Architekturlinie | `jarvis/rebuild-v1` | `c222601` |
| Kontakte-/Kalenderlinie (Ursprung) | `handoff/contacts-read-flow-2026-07-29` | `1f03bfa` |
| Kontakte-/Kalenderlinie (fortgeführt) | `spike/calendar-foundation-intel-2026-08-04` | `8e6e206` vor der Integration |
| Werkzeuglinie (integriert) | `tooling/gates-v1` | `4e47144` |

Die Merge-Base beider Entscheidungslinien ist mechanisch mit
`git merge-base --all` bestimmt, eindeutig und lautet `d037cb6`. Sie wird bei
jedem Gate-Lauf erneut abgeleitet und nie aus einem Manifest übernommen.

### §6.2 Befund (Ancestry-genau)

Beide Linien vergaben nach der Merge-Base unabhängig dieselben Nummern: fünf
DEC-Nummern und zwei ADR-Nummern.

| Nummer | Belegung `jarvis/rebuild-v1@c222601` | Belegung der Kontakte-/Kalenderlinie |
|---|---|---|
| `DEC-044` | Übernahme des OpenJarvis-Reuse-Audit-Kanons | Architektur der Apple-Contacts-Provider-Mutationen eingefroren |
| `DEC-045` | Verbindliche Modulreihenfolge bis Modul 3 | App-Prozess-Mutationskanal eingefroren |
| `DEC-046` | Autonomie- und Hintergrundaktionsmodell | DEC-D06 entschieden: keine native R2-Zweitbestätigung |
| `DEC-047` | KI-Arbeit, Internet, Browser- und App-Steuerung als verbindliches Zielbild | Intel-Zweig des Kontaktmoduls eingefroren |
| `DEC-048` | Hausverwaltungs-Systemgrenzen und Workspace-Sicherheitskontexte | Kalender-Fundament-Spike (Intel) freigegeben und begrenzt |
| `ADR-0019` | Verbindliche Modulreihenfolge und 100-Prozent-Modulvollendung | Architektur der Apple-Contacts-Provider-Mutationen (Create/Update/Delete) |
| `ADR-0020` | Übernahme der OpenJarvis-Reuse-Entscheidungen und kontrollierte Suchprojektion | Der App-Prozess-Mutationskanal (Backend → Claim → Frontend → Tauri → Contacts.framework → Settle) |

Die ADR-Nummern 0021 bis 0024 sind ausschließlich auf `jarvis/rebuild-v1`
belegt. Die ADR-Nummern 0001 bis 0018 sind auf beiden Linien identisch belegt.

### §6.3 Vollzogene Auflösung

Die Belegung von `jarvis/rebuild-v1` ist **kanonisch** (früher vergeben, Teil
des eingefrorenen Architektur-Freeze) und bleibt vollständig unverändert. Die
Artefakte der Kontakte-/Kalenderlinie wurden nach fester Eigentümerfestlegung
auf die nächsten freien Nummern umnummeriert. Titel und Inhalte blieben dabei
unverändert; geändert wurden ausschließlich ID, Dateiname, Überschrift,
Registereintrag und die davon abhängigen Verweise.

| Alt-ID (Kontaktelinie) | Neu-ID | Exakter Titel |
|---|---|---|
| `DEC-044` | **`DEC-051`** | Architektur der Apple-Contacts-Provider-Mutationen eingefroren |
| `DEC-045` | **`DEC-052`** | App-Prozess-Mutationskanal eingefroren |
| `DEC-046` | **`DEC-053`** | DEC-D06 entschieden: keine native R2-Zweitbestätigung |
| `DEC-047` | **`DEC-054`** | Intel-Zweig des Kontaktmoduls eingefroren |
| `DEC-048` | **`DEC-055`** | Kalender-Fundament-Spike (Intel) freigegeben und begrenzt |
| `ADR-0019` | **`ADR-0025`** | Architektur der Apple-Contacts-Provider-Mutationen (Create/Update/Delete) |
| `ADR-0020` | **`ADR-0026`** | Der App-Prozess-Mutationskanal (Backend → Claim → Frontend → Tauri → Contacts.framework → Settle) |

Dateien: `docs/adr/ADR-0025-provider-mutation-architecture.md` und
`docs/adr/ADR-0026-app-process-mutation-channel.md`.

Vor der Umnummerierung wurde tokengenau und unicode-normalisiert über die
vollständigen Bäume beider Entscheidungslinien und der Werkzeuglinie geprüft,
dass alle sieben Ziel-IDs als Zuweisung frei waren. Die dabei gefundenen
Nichtzuweisungen — ein synthetisches Testfixture und die Ankündigung genau
dieser Umnummerierung in diesem Paragraphen — sind klassifiziert und in
`config/governance/b0a-3-id-migration.json` festgehalten.

Die Tabelle Alt-ID → Neu-ID ist **historischer Auflösungsnachweis**, keine
aktuelle Doppelvergabe. Nach der Auflösung gilt: null offene Kollisionen,
keine neue ID außerhalb dieser sieben, keine zusätzliche ADR-Datei.

### §6.4 Referenzmigration

Der frühere Referenzplan dieses Paragraphen war ausdrücklich bei Ausführung
erneut per Suche zu verifizieren. Beides ist geschehen: die deklarierte Liste
wurde vollständig mitgezogen und zusätzlich durch eine Repositorysuche über
Dokumentation, Entscheidungs- und ADR-Register, Quellcode, Codekommentare,
Tests, Testnamen, Fixtures, Snapshots, Skripte, Hooks, Gate-Manifeste sowie
Beispielausgaben und Handoff-Dateien ergänzt und gegengeprüft.

Deklariert waren: die beiden ADR-Dateien einschließlich Querverweisen,
`docs/personal-jarvis/00-architecture-index.md`, `17-deferred-decisions.md`,
`decisions-register.md`, `modules/contacts.md`,
`calendar-foundation-spike-2026-08-04.md`,
`contacts-mutation-phase-a-2026-08-03.md`,
`contacts-native-create-intel-2026-08-04.md`,
`contacts-native-update-delete-intel-2026-08-04.md`,
`docs/testing/contacts-x86_64-create-live-2026-08-01.md`,
`docs/testing/contacts-x86_64-create-local-live-2026-08-01.md` sowie die
Kommentar-Referenzen in `frontend/src-tauri/build.rs`,
`objc/JCContactsCreate.m`, `src/bin/contacts_write_helper.rs`, `src/lib.rs`,
`src/contacts_create.rs`, `src/contacts_execution.rs`,
`frontend/src/personal/contacts/api.ts`, `status/ContactsStatusSurface.tsx`,
`components.test.tsx` und `data/source.ts`.

Die Laufzeitsuche ergänzte diese Liste um weitere Fundstellen in
`src/personaljarvis/**`, `tests/personal/**`, `native/contacts-bridge/**`,
`frontend/src-tauri/**` und `docs/**`. Der Abgleich von deklarierter Liste und
tatsächlichen Treffern läuft mechanisch im Gate `of-reference-migration`. Ein
bloßes Ersetzen von Zeichenketten genügt nicht: jede Fundstelle wird gegen
Titel und Linie geprüft, damit kein Verweis auf die falsche Entscheidung der
`rebuild-v1`-Linie entsteht.

Nicht verändert wurden Schema, Migrationslogik, Bundle-Identität, Signierung
und TCC-relevante Identität; in Migrationen und im nativen Sidecar betraf die
Migration ausschließlich Kommentare und Docstrings.

## §7 Implementierungsbasis (Empfehlung nach tatsächlicher Ancestry)

**Der spätere Kalender-Implementierungsbranch zweigt vom Baseline-Commit
dieses Dokuments auf `spike/calendar-foundation-intel-2026-08-04` ab**
(dem direkten Nachfolger von `f6f973a`).

Begründung:

1. Er **enthält** den eingefrorenen Kontakte-Stand `1f03bfa` und damit den
   aktuellen generischen Mutation Core (Outbox-Claim, verbrauchte Freigabe,
   Einmalwächter, `outcome_unknown`-Automat, Transportvertrag v1) sowie die
   Fundament-Spike-Erkenntnisse und diese Baseline.
2. `jarvis/rebuild-v1` ist von dort **sauber integrierbar**: Die Divergenz
   besteht aus genau einem Docs-Commit (`c222601`). Ein späterer Merge
   bringt ausschließlich Dokumentation; die erwartbaren Konflikte sind die
   ADR-Nummern (§6) und wenige `personal-jarvis`-Dokumente
   (`00-architecture-index`, `17`, `decisions-register`,
   `modules/contacts.md`) — alle durch den Plan in §6 aufgelöst.
3. Ein Abzweig von `jarvis/rebuild-v1` selbst wäre falsch: Er enthielte
   **keinen** Mutation Core und keinen Kontakte-Produktcode.
4. Ausdrücklich **kein** Merge, Rebase oder Cherry-pick jetzt; die
   Integration mit rebuild-v1 erfolgt im Rahmen des Kontakte-Gates
   „Integration des Handoffs in `jarvis/rebuild-v1`" (DEC-050 der Linie `jarvis/rebuild-v1`) bzw.
   spätestens vor der Kalender-Fertigmeldung.

## §8 Nicht Gegenstand

Kein Produktcode, keine Migration, keine Route, keine UI-Fläche, keine
Änderung an Entitlements, Signierung oder Build. Keine neue ADR-Datei
(§6 Nr. 5). Keine Veränderung der eingefrorenen Kontakte- oder
Architekturstände. Dieses Dokument nimmt keine Eigentümerentscheidung
vorweg, die im Fundament-Spike §12 als offen geführt ist, soweit sie nicht
in §2 ausdrücklich entschieden wurde.

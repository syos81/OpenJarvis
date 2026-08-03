# Kontakte-Frontend: Apple-Neuaufbau (Intel-Strukturphase), 2026-08-02

Branch `feat/contacts-apple-frontend-2026-08-02`, Basis `7363538`, isolierter
Worktree. Dieser Auftrag baut die Struktur; die pixelgenaue Abnahme gegen die
M2-Referenz ist **ausdrücklich offen**.

## 1. Verbindlicher Referenzvertrag

1. **Hauptreferenz ist die macOS-Kontakte-App auf dem M2-Pro-Mac des
   Benutzers.** Sie ist zum Zeitpunkt dieses Auftrags nicht verfügbar —
   weder als Gerät noch als Screenshot-Satz.
2. **Intel macOS 12.7.6 ist Kompatibilitätsziel, nicht Designreferenz.**
   Was hier gebaut wird, muss auf Monterey laufen und bedienbar sein; wie es
   final aussieht, entscheidet die M2-Referenz.
3. **Alle Maße ohne M2-Beleg sind vorläufig** und tragen im Token-System das
   Präfix-Kommentar `M2-VORLÄUFIG`. Es gibt keine verstreuten Magic Numbers:
   jede Grösse, Farbe, Dauer und Typografiestufe der Kontakte-Oberfläche
   kommt aus `frontend/src/personal/contacts/tokens.css`.
4. **Zulässige Abschluss-Einstufung dieses Auftrags:** „strukturell und
   funktional vorbereitet; M2-Pixelabnahme offen." Eine Behauptung
   „pixelgenau 1:1" ist unzulässig und wird nicht getroffen.
5. Später anhand der M2-Referenz anzupassen (zentral über Tokens, gezielt
   über Komponenten): Spaltenbreiten, Toolbar-Höhe, Seitenleistenabstände,
   Zeilenhöhen, Typografie und Schriftgewichte, Divider, Farben, Materialien,
   Schatten, Eckenradien, Icon- und Avatargrössen, Detailabstände sowie
   Hover-/Focus-/Selection-Zustände.

### M2-Abnahmecheckliste (späterer Auftrag auf dem M2 Pro)

Benötigte Referenzaufnahmen der echten macOS-Kontakte-App, jeweils Light
**und** Dark, Standardfenster und maximiert, als unskalierte
Retina-Screenshots:

1. Dreispaltansicht mit ausgewähltem Kontakt (Messbasis für Spaltenbreiten,
   Zeilenhöhe, Abschnittsmarker, Auswahlfarbe).
2. Sidebar mit mehreren Accounts und Gruppen (Abstände, Einzüge,
   Kopfzeilen, Auswahlzustand).
3. Toolbar im Ruhezustand und mit fokussiertem Suchfeld (Höhe, Material,
   Suchfeldform).
4. Detailansicht eines vollständigen Kontakts (Hero-Aufbau, Avatargrösse,
   Feldgruppen, Label-Spaltenbreite, Divider).
5. Detailansicht eines fast leeren Kontakts.
6. Bearbeitungsmodus (Feldrahmen, Add-/Remove-Steuerungen, Label-Menüs,
   Knopfleiste).
7. Leerer Zustand („Keine Kontakte") und leeres Suchergebnis.
8. Hover-, Fokus- und Auswahlzustände je Zeile (Video oder Einzelbilder).
9. Fenster bei Mindestgrösse.
10. Systemschrift-Metrik: ein Bildschirmfoto mit Textlineal oder die
    gemessenen Punktgrössen der Listen-/Detail-Typografie.

Abnahmereihenfolge auf dem M2 Pro: (a) Referenzaufnahmen erstellen,
(b) Token-Abgleich (eine Runde nur `tokens.css`), (c) gezielte
Komponentenkorrekturen, (d) visueller Abgleich Szene für Szene,
(e) ARM64-Build + native Abnahme inkl. der weiterhin offenen
ARM64-Lifecycle-/Shutdown-/AppSave-Abnahmen.

## 2. Bestandsaudit (vor dem Umbau)

Stack: React 19, react-router 7 (eine Layout-Route, `/contacts`),
zustand 5 (vom Kontakte-Modul bewusst ungenutzt), Tailwind v4 (Konfiguration
rein in `src/index.css`), shadcn `base-nova` auf `@base-ui/react`,
lucide-react, vitest + Testing Library, keine Query-Lib, keine
Virtualisierung, keine Split-Panes im ganzen Projekt. Tauri-Fenster
1280×800, min. 900×600.

Kontakte-Modul vor dem Umbau: fünf Dateien unter `src/personal/contacts/`
— `ContactsPage.tsx` (1609 Zeilen, die gesamte Oberfläche), `components.tsx`
(326 Zeilen Bausteine inkl. Modal mit Fokusfalle), `api.ts` (675 Zeilen
vollständiger HTTP-Client + genau ein Tauri-Command für den TCC-Dialog) und
zwei Testdateien (zusammen ~1760 Zeilen inkl. statischer
Quelltext-Verträge).

Einordnung der Altkomponenten:

| Baustein | Entscheidung |
|---|---|
| `api.ts` (Client, Typen, Fehlervertrag) | **behalten**, unverändert |
| `components.tsx`: Modal, ErrorState, LoadingState, EmptyState, Chip, StateChip, FieldStateBadge, ChangeTable, Label-Maps | **intern wiederverwenden** |
| `SyncPanel` | **neu strukturieren** → Statusfläche (nicht mehr über der Liste) |
| `ContactList` | **ersetzen** → `ContactsListPane` (Auswahl statt Navigation, Abschnitte, Tastatur) |
| `ContactDetailView` | **ersetzen** → `ContactDetailPane` (Hero, Feldzeilen, ruhige Hierarchie) |
| `CreateDialog`/`UpdateDialog` | **neu strukturieren** → `ContactEditor` (Bearbeitungsmodus im Detailbereich) |
| `DeleteDialog`, `PreviewDialog` | **behalten** (als Dialoge der neuen Struktur) |
| `ApprovalBoard`, `MutationList`, `MutationDetailView`, `kannAusfuehren` | **intern wiederverwenden** → `ContactsStatusSurface` |
| Tab-Navigation der alten Seite | **entfernen** (ersetzt durch Workspace + Statusfläche) |

Es entfällt keine fachliche Funktion: jeder Endpunkt, jeder Zustand und
jeder Sicherheitsvertrag der alten Seite hat in der neuen Struktur einen
Ort.

Technische Schulden im Bestand, die dieser Umbau behebt:

- `--color-text-muted`, `--color-danger`, `--color-surface-2` wurden benutzt,
  waren aber **nirgends definiert** (teils ohne Fallback). Jetzt zentral in
  `tokens.css` definiert und auf bestehende Jarvis-Tokens gemappt.
- Monolith mit 1609 Zeilen → klar geschnittene Komponenten.
- Detailansicht ersetzte die Liste (Einspalten-Navigation) → echtes
  Dreispalten-Layout.
- Maße/Farben lagen verstreut in Inline-Styles → zentrale Tokens.

## 3. Zielarchitektur

```
src/personal/contacts/
├── ContactsPage.tsx          — dünner Einstieg (Route, Fehlerrahmen)
├── api.ts                    — unverändert
├── components.tsx            — geteilte Bausteine (unverändert)
├── tokens.css                — ALLE Kontakte-Design-Tokens (--pjc-*)
├── data/
│   ├── source.ts             — ContactsDataSource-Vertrag + API-Quelle
│   ├── fixtures.ts           — synthetische Kontakte (deterministisch)
│   └── fixtureSource.ts      — Demo-Quelle inkl. Fake-Vorgängen
├── workspace/
│   ├── ContactsWorkspace.tsx — Dreispalten-Gerüst, Auswahl- und Fokusmodell
│   ├── ContactsToolbar.tsx   — Toolbar + Suchfeld + Statuszugang
│   └── PaneDivider.tsx       — ziehbare, tastaturbedienbare Spaltentrenner
├── sidebar/
│   └── ContactsSidebar.tsx   — Alle Kontakte, Accounts, Kategorien
├── list/
│   └── ContactsListPane.tsx  — Abschnitte, Auswahl, Tastatur, Fensterung
├── detail/
│   └── ContactDetailPane.tsx — Hero, Feldgruppen, Adressen, Notiz
├── editor/
│   └── ContactEditor.tsx     — Bearbeiten/Fertig/Abbrechen, Validierung
└── status/
    └── ContactsStatusSurface.tsx — Quelle/Abgleich, Freigaben, Vorgänge
```

Datenfluss: `ContactsWorkspace` besitzt den Kontakte-Datenzustand (geladen
über eine `ContactsDataSource`), die Auswahl (`auswahlId`), den Suchtext,
den Sidebar-Filter und den Bearbeitungszustand. Alle Panes sind
Präsentationskomponenten mit Callbacks; API-Logik liegt ausschliesslich in
`data/` und `api.ts`. Die Statusfläche lädt ihre Daten selbst (wie bisher),
ist aber räumlich von der Apple-Ansicht getrennt.

Zustandsmodell (Workspace): `quelle: 'api' | 'fixtures'`,
`kontakte: ContactSummary[]` (vollständig geladen, lokal gefiltert),
`ladezustand: laden | bereit | fehler`, `auswahlId`, `sichtbareListe`
(abgeleitet aus Suche + Sidebar-Filter, deterministisch sortiert),
`bearbeitet: ContactDraft | null`, `statusOffen: boolean`,
`spaltenbreiten` (deterministische Startwerte aus Tokens, nicht
persistiert — es existiert bewusst keine Contacts-eigene Präferenzschicht,
und der zustand-Store bleibt laut Statiktest tabu).

## 4. Tastaturvertrag

| Kontext | Taste | Wirkung |
|---|---|---|
| Liste | ↑ / ↓ | Auswahl bewegen (bleibt im Filter stabil) |
| Liste | Home / End (⌘↑/⌘↓ folgt mit M2-Abnahme) | erste/letzte Zeile |
| Liste | Enter | Detail fokussieren |
| Suchfeld | Escape | Suche leeren; ist sie leer: Fokus zurück zur Liste |
| überall | ⌘F | Suchfeld fokussieren |
| Trenner | ← / → | Spaltenbreite in Schritten ändern |
| Trenner | Enter/Space | kein Effekt (kein Toggle) — dokumentiert |
| Editor | Escape | Abbrechen (mit Rückfrage bei Änderungen) |
| Dialoge | Escape / Tab-Zyklus | wie bisher (Fokusfalle in `Modal`) |
| Fokusreihenfolge | Toolbar → Sidebar → Liste → Detail | via Tab |

Verschwindet der ausgewählte Kontakt aus dem Filter, bleibt die Auswahl-ID
erhalten, die Liste zeigt keine Markierung, der Detailbereich zeigt den
Kontakt weiter mit dem Hinweis „nicht im aktuellen Filter". Doppelklick hat
**keine** Sonderfunktion (dokumentiert); Bearbeitung startet nie durch
blosses Klicken.

## 5. Fixture-Strategie (Demo-Modus)

- Ausschliesslich synthetische, deterministische Kontakte
  (`data/fixtures.ts`): erfundene Namen wie „Testperson Alpha", Domains
  `example.invalid`, Nummern aus dem fiktiven Bereich `+49 000 …`,
  Umlaute/Sonderzeichen, lange Werte, leere Kontakte, mehrere synthetische
  Accounts und Kategorien; Grössen 100/1000/10000 für Performanceprüfungen.
- **Standardmässig aus.** Aktivierung nur über die Statusfläche →
  „Demo-Modus" mit ausdrücklicher Bestätigung (zwei bewusste Schritte),
  gilt nur für die laufende Sitzung (kein localStorage), sichtbares Banner
  „Demo-Modus: synthetische Kontakte" mit „Beenden".
- Im Demo-Modus wird **keine** API-Funktion des Kontakte-Clients
  aufgerufen; Vorbereiten/Freigeben erzeugt ausschliesslich Fake-Vorgänge
  im Speicher — darunter bewusst je ein Vorgang in `awaiting_approval`,
  `outcome_unknown` und `manual_decision_required`, damit alle
  Jarvis-Zustände ohne produktive Daten sichtbar sind.
- Kein Mischbetrieb: die Quelle wird als Ganzes getauscht.

## 6. Bearbeitungsmodus und Mutationsgrenzen

„Fertig" erzeugt im API-Betrieb genau die vorhandene, sichere
Vorbereitung (`prepareUpdate`/`prepareDelete` → Vorschau → Freigabe); es
wird keine neue Mutationsarchitektur gebaut und kein Provider-Write
ausgelöst. Der Feldvertrag v1 deckt die sechs Skalarfelder ab; Mehrwertfelder
(E-Mail/Telefon/Adresse) sind im API-Betrieb im Editor sichtbar, aber als
„erst mit erweitertem Feldvertrag übertragbar" gekennzeichnet und nicht
Teil der Vorbereitung. Im Demo-Modus ist alles editierbar und mündet in
Fake-Vorgänge. Die Löschaktion führt in beiden Betriebsarten nur bis zur
Vorbereitung/Bestätigung, nie zur Ausführung.

## 7. Accessibility

Rollen: Sidebar `role="navigation"`, Liste `role="listbox"` mit
`aria-activedescendant`, Zeilen `role="option"` + `aria-selected` +
`aria-setsize`/`aria-posinset` (wegen Fensterung), Trenner
`role="separator"` mit `aria-orientation`/`aria-valuenow`/-min/-max,
Detailbereich `role="region"` mit `aria-label`, Statusflächen wie bisher
(`role="status"`/`role="alert"`), Editorfehler über `aria-describedby`.
Fokus sichtbar über `--pjc-focus-ring` (nie nur Farbe), Klickziele
mindestens `--pjc-hit-target`. `prefers-reduced-motion` schaltet die
(ohnehin kurzen) Übergänge ab. Auswahl-, Hover- und Fehlzustände tragen
neben Farbe immer Form (Haken/Rahmen/Text).

Bekannte Monterey-/WKWebView-Grenzen: kein natives `::backdrop`-Material
(Vibrancy) — Hintergründe sind opake Token-Farben; VoiceOver in WKWebView
meldet `aria-activedescendant`-Wechsel teils verzögert; `scrollbar-gutter`
ist nicht verfügbar (Fallback: stabile Padding-Reserve);
Systemakzentfarbe ist aus dem WebView nicht auslesbar (Token statt
`accentcolor`). **Live-Befund der Intel-Abnahme:** WKWebView zeichnete die
Mittelspalte bei Trenner-Drags und Hover-Zuständen unzuverlässig neu.
Gegenmassnahmen: (a) die Spaltenreihe ist ein CSS-Grid, (b) der
Listen-Scrollcontainer liegt auf einer eigenen erzwungenen
Kompositions-Ebene (`translateZ(0)`), (c) Maus-Drags am Trenner wenden
die Breite erst beim Loslassen an und zeigen währenddessen eine
Führungslinie (Tastaturschritte wirken sofort), (d) das Drag-Ende stösst
ein `resize`-Ereignis an. Zusätzlich reserviert die Toolbar rechts
`--pjc-toolbar-reserve` für die dort schwebende globale Approval-Glocke
der App.

Hover-Affordanz (Nutzerwunsch aus der Live-Abnahme): Zeilen und
Schaltflächen animieren beim Überfahren den Hintergrund
(`--pjc-hover-bg`, `--pjc-duration-fast`), gefüllte Primärknöpfe hellen
auf (`.pjc-primary`); `prefers-reduced-motion` setzt die Dauern auf 0.
Im Demo-Modus sind Update/Delete-Capabilities bewusst aktiv, damit der
Bearbeitungsmodus ohne produktive Daten voll erlebbar ist —
`execute` lehnt dort grundsätzlich mit stabiler Kennung
`demo_execute_blocked` ab. Die Notiz-Nichtlesbarkeit erscheint als leise
gedämpfte Zeile mit Tooltip statt als Warnkasten.

## 8. Performance (gemessen am 2026-08-02, Intel x86_64)

Die Liste rendert bis 400 Zeilen vollständig; darüber fenstert sie
(eigene, schlanke Fensterung mit festen Zeilenhöhen aus Tokens,
Überhang `--pjc-list-overscan`). Tastaturnavigation, Auswahlstabilität,
Abschnittsmarker und Screenreader-Attribute funktionieren unabhängig vom
Fenster (Testbeleg: `aria-setsize=10000` bei < 120 DOM-Zeilen). Suche
filtert lokal, entprellt (150 ms), ohne die Oberfläche zu blockieren:

| Kontakte | Erzeugung | Sortierung | Suche Name | Suche E-Mail/Tel. |
|---|---|---|---|---|
| 100 | 21 ms | < 1 ms | 2 ms | < 1 ms |
| 1.000 | 3 ms | 2 ms | 8 ms | 6 ms |
| 10.000 | 77 ms | 9 ms | 50 ms | 45 ms |

Alle Werte liegen unter der Entprellzeit; die Suche blockiert damit auch
bei 10.000 Kontakten keinen Frame spürbar. Auswahl bleibt über
Filterwechsel stabil (Testsuite B).

## 8a. Dev-Szenarien für die Baseline

Nur im Vite-Dev-Betrieb (`import.meta.env.DEV`; im Produktionsbundle toter
Code): URL-Parameter `pjcDemo=<n>`, `pjcAuswahl=<index>`, `pjcSuche=<text>`,
`pjcKategorie=<rolle>`, `pjcEditor=1`, `pjcStatus=<tab>`, `pjcTheme=dark|light`
stellen deterministische Zustände her (Screenshots, manuelle Prüfung).
`pjcTheme` wird synchron in `main.tsx` angewendet; zwei dev-gatete Guards in
`App.tsx` halten Theme-Effekt und Opt-In-Dialog aus den Szenarien heraus.
Im gepackten Tauri-Betrieb existiert keine Adresszeile — der Demo-Modus
läuft dort ausschliesslich über die Statusfläche (zwei bewusste Schritte).

## 9. Intel-Strukturbaseline

Elf Screenshots (Standard Light/Dark, 900×600, 1600×1000, Sidebar-Auswahl,
Kontakt ausgewählt, leerer Zustand, Suchergebnis, Bearbeitungsmodus,
Approval-Fake, Fehlerzustand) liegen **ausserhalb** des Repositories unter
`~/jarvis-contacts-intel-baseline-2026-08-02/`. Sie zeigen ausschliesslich
synthetische Kontakte und sind die vorläufige Intel-Strukturbaseline —
keine M2-Referenz. Erzeugt mit puppeteer-core gegen den Vite-Dev-Server
(Pixel-verifizierte Light/Dark-Paare).

## 10. Mitgezogene Fremdstellen

- `tests/personal/contacts/test_container_inventory.py`: der
  Schreibweisen-Abgleich der Ablageort-Arten liest jetzt
  `editor/dialogs.tsx` statt des aufgelösten Seitenmonolithen.
- `App.tsx`/`main.tsx`: zwei dev-gatete Guards (siehe 8a), im
  Produktionsverhalten wirkungslos.
- `tokens.css` definiert die vom Bestand benutzten, vorher undefinierten
  Variablen `--color-text-muted`, `--color-danger`, `--color-surface-2`.

## 11. Intel-Liveabnahme: tatsächlicher Verlauf (2026-08-02/03)

Damit der Nachweis nicht mehr sagt, als er belegt: die interaktive
Abnahme lief **nicht vollständig synthetisch**.

- Beim Öffnen der Kontakte-Seite lud und zeigte die Oberfläche den
  **produktiven, real synchronisierten Kontaktbestand** (117 Kontakte)
  — ausschliesslich **lesend**.
- Es wurde **kein** Sync gestartet, **kein** Provider-Write ausgeführt und
  **keine** produktive Mutation vorbereitet oder ausgeführt.
- Die interaktiven Prüfungen von Bearbeitungsmodus, Statusflächen
  (Freigaben, `outcome_unknown`, manuelle Klärung) und Performance liefen
  anschliessend im Demo-Modus mit synthetischen Daten.
- Die produktiven Datenbankaggregate (Kontakte, externe Identitäten,
  Tombstones, Freigaben, Mutationen, Audit-Ereignisse) waren vor und nach
  der gesamten Abnahme **identisch**.

Die Screenshots der Intel-Strukturbaseline (Abschnitt 9) enthalten
dagegen ausschliesslich synthetische Kontakte; sie entstanden im
Demo-Modus gegen den Dev-Server.

Aus dieser Abnahme stammen die in Abschnitt 7 beschriebenen
WKWebView-Korrekturen (Trenner-Neuzeichnung, Hover-Affordanz, Freiraum
für die global schwebende Approval-Glocke) sowie die leise Notiz-Zeile
und die im Demo-Modus aktiven Update-/Delete-Capabilities.

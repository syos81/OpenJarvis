# B0c Handoff — Governance: Konfigurationsbindung, zielgebundene Freigabe, Reservierungsregister, Abnahmeprofile

Alle Angaben stammen aus maschinellen Gate-Ergebnissen, sanitierter Evidenz,
deklarativen Manifesten sowie Commit- und Branchdaten. Rohlogs werden nicht
zitiert.

## §1 Lage

| Größe | Wert |
|---|---|
| Branch | `spike/calendar-foundation-intel-2026-08-04` |
| Ausgangscommit | `06b7d7e3740325a12c4b1a2c41d3192e4f696c14` |
| Commit des Abschlusslaufs | `2c571423e900b38a7a3f550a79af719ab8b57dd9` |
| Geänderte Dateien seit Blockstart | 35 Dateien, 8502 Einfügungen, 4 Löschungen |
| `git diff --check` | ohne Befund |
| Blockmanifest | `config/gates/blocks/b0c-governance.json`, 63 Prüfungen |

## §2 Phasenergebnisse

| Phase | Ergebnis | Prüfungen |
|---|---|---|
| `preflight` | `pass` | 11 |
| `targeted` | `pass` | 13 |
| `offline-final` | `pass` | 30 |
| `platform-live` | `pass` | 5 |
| `module-final` | `pass` | 4 |

Maschineller Gesamtstatus: **`pass`**. Keine Phase ist `not_applicable`, keine
Phase ist `blocked`, kein Ergebnis wurde umgedeutet.

Baseline: deklariert `7986bee`, nicht aufgelöst, **nicht verwendet**;
Ursachensignaturversion `cs-1`; Cachezustand `not_used`. Es gibt in diesem
Block kein `pass_with_baseline`.

## §3 Merkmalsprüfung gegen den unmittelbaren Vorgänger

Vorgänger ist B0b (`config/gates/features/b0b-calendar-k1.lineage.json`), per
SHA-256 gebunden.

| Größe | Wert |
|---|---|
| erwartet | 133 |
| zugeordnet | 133 |
| geändert | 0 |
| fehlend | 0 |

Eigene Merkmale: Präfix `B0C-`, 30 erwartet, 30 nachgewiesen, 0 fehlend. Jedes
eigene Merkmal ist an eine Gate-Prüfung, einen Test oder eine wirklich
vorhandene Datei gebunden.

Erhaltung der Vorgängerlinien, aus `mf-preservation`: `B0A1-` 24/24, `B0A2-`
38/38, `B0A3-` 14/14, `B0A4-` 35/35.

## §4 Prüfungen im Einzelnen

Strukturelle Signaturtests, Evidenz- und Canary-Tests sowie die
Hook-Testmatrix sind in diesem Block **nicht** als eigene Manifestprüfungen
geführt, sondern laufen innerhalb von `of-tooling-tests` über den vollständigen
Baum `tests/tooling`. Diese Prüfung ist `pass`. Das ist eine Aussage über die
Abdeckung, nicht über gleichwertige Einzelnachweise.

`of-historical-integrity` ist `pass`: für B0a-1 bis B0a-4 ist die gebundene
Evidenz vollständig vorhanden, `evidence_absent=0` in allen vier Fällen.

## §5 Was dieser Block festgestellt hat

**Regel R4, Schema vor Daten.** Wird ein Konfigurationsformat erweitert, ist
der akzeptierende Leser spätestens im selben Commit zuerst wirksam. Allgemein
durchgesetzt: 74 Konfigurationsdateien sind an je genau einen zuständigen
Leser gebunden, und eine ungebundene Datei, eine veraltete Bindung, zwei
Bindungen für eine Datei sowie ein Feld, das kein Leser akzeptiert, fallen
jeweils.

**Zielgebundene Freigabe statt Ausnahme.** `push` und `update-ref` werden
ausschließlich gegen ein Wegwerf-Bare-Repository unterhalb der deklarierten
Fixture-Wurzel freigegeben. Gesperrt bleiben das echte `origin` namentlich und
über jeden darauf auflösenden Remote-Alias, jede deklarierte geschützte Ref,
ein Symlink der ausbricht oder umlenkt, ein `..`-Pfad, ein erzwungener
Refspec, jede Option, ein zweites Befehlssegment und ein erhöhter Befehl. Die
Freigabe braucht keinen anwesenden Eigentümer — das ist der Grund, warum ein
Gate von ihr abhängen darf.

**Reservierungsregister.** Schema, Modell, Speicher und Werkzeug liegen vor.
Das Register ist ein reines Anhängeprotokoll mit Hashkette; die Ref wird mit
Compare-and-Swap bewegt. Das Werkzeug vergibt nichts und veröffentlicht
nichts.

**Abnahmeprofile.** Ergebnis `not_justified`, berechnet statt behauptet, aus
zwei Tatsachen: keine Einheit trägt zugleich ein Abnahmeprofil und eine
Pflichtensignatur, und jedes der sieben Blockmanifeste trägt eine eigene,
paarweise verschiedene Signatur. Kein Profilartefakt, kein Profilschema. Die
nie definierten Kürzel sind dauerhaft gesperrt; die K1-Abwesenheitsprüfung
bleibt unverändert erhalten.

**Korrekturvermerk zu STOP 2.** Die B0b-Aussage zur Nummernfreiheit beruhte
auf einer defekten Methode — ein Textscan, der Belegung nicht von Erwähnung
unterscheiden kann. Der korrigierte Scanner **bestätigt** sie: über beide
Linien `DEC-001`–`DEC-055` und `DEC-D01`–`DEC-D17` lückenlos, erste unbelegte
Nummern `DEC-056` und `DEC-D18`. Geändert hat sich nicht das Ergebnis,
sondern was es trägt. Die historische Aussage wird **nicht** umgeschrieben;
der Vermerk steht daneben, in
`config/gates/history/b0c-stop2-correction.json`.

## §6 Guard-Aktivierung

Der Block wurde gegen die tatsächlich aktive Guard-Version abgenommen:
`1.1.0`. Der Kandidat ist `1.2.0` und **nicht** aktiv.

Kein Manifest übergibt `--expect-version`, die `platform-live`-Modi arbeiten
auf dem, was installiert ist, und die Offline-Runner sind Unterprozesse, die
der `PreToolUse`-Hook nie sieht. Die Aktivierung ist damit **Folge** dieser
Abnahme, nicht ihre Voraussetzung, und ist eine Eigentümerhandlung nach
Blockabschluss.

## §7 Ausdrückliche Bestätigungen

- kein Produktcode geändert — die 35 geänderten Pfade liegen vollständig in
  Werkzeug und Governance, geprüft gegen den Blockstart,
- kein Live-Lauf gegen ein produktives System, keine Provider- oder
  Netzbeteiligung,
- kein Merge, kein Rebase, kein Cherry-pick, kein Tag, kein Release,
- kein Force-Push, kein automatischer Push,
- keine DEC- oder ADR-Nummer vergeben, keine reserviert,
- die kanonische Governance-Ref ist **nicht** angelegt worden,
- kein Folgeblock begonnen.

Pushstatus: **`not_performed_owner_action`**.

## §8 Offene Befunde

1. **Claude-Code-Anwendung als offene Vertrauenswurzel** — unverändert.
2. **Schutzprotokoll nach vorn fälschbar** — unverändert.
3. **Backstop-Ebene überschätzt bewusst** — unverändert; sie schlägt auch bei
   bloßer Erwähnung an. In diesem Block zweimal praktisch bestätigt.
4. **Selbstaussperrung bei ungültiger Guard-Konfiguration** — neu
   dokumentiert im Vertrauensmodell. Eine Konfiguration, die ihr eigener
   Lader nicht annimmt, erzeugt keine Entscheidung und sperrt jede
   Werkzeugnutzung, Lesen eingeschlossen. Nur der Eigentümer stellt wieder
   her. R4 beseitigt die wahrscheinlichste Ursache, nicht die Eigenschaft.
5. **Abgelaufene und versionsfremde Ausnahmeobjekte** — der ursprüngliche
   Deny-Grund wird von einem Korruptionsfehler verdeckt. Kein Blocker für
   diesen Block: keine erforderliche Phase ist davon berührt, alle fünf sind
   `pass`. Eigener Guard-Härtungsblock direkt nach B0c; die beiden Objekte
   sind vom Eigentümer nach `~/jarvis-guard-evidence/` verschoben und als
   Evidenz aufbewahrt, nicht gelöscht.
6. **Registerdaten existieren noch nicht.** Dieser Block liefert Schema,
   Modell, Speicher und Werkzeug. Das Anlegen der kanonischen Ref und der
   Genesis-Block sind Eigentümerhandlungen.

## §9 Für den nächsten Block

1. **Guard-Härtung** (unmittelbar nach B0c): abgelaufene und versionsfremde
   Ausnahmen werden ignoriert und eingesammelt, der ursprüngliche Deny-Grund
   bleibt unverändert erhalten.
2. **Registrierung als Governance-Entscheidungen**, sobald das
   Reservierungsregister läuft: R1, R2, R3, R4, die Zwei-Test-Regel,
   Bericht-als-Folge und die Eigentümergrenzen. `CLAUDE.md` bleibt danach nur
   noch Verweis.
3. **Oberflächenparität als allgemeine Fähigkeit**, mit den Instanzen
   Kalender und Kontakte — nicht als zwei Sonderfälle.
4. **Mechanische Architekturklassifikation der fünf offenen K1-Gates**
   (`K1-O01`, `K1-O02`, `K1-O03`, `K1-O05`, `K1-O06`): je Gate ausweisen, was
   `x86_64`-abnehmbar ist, was `arm64` verlangt und was nicht
   architekturabhängig ist, jeweils mit Beleg. Diese Klassifikation ist in
   B0c **nicht** erstellt worden und wird hier auch nicht vorweggenommen.

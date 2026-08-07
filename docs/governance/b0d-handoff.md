# B0d Handoff — Guard-Härtung: Ausnahmequalifikation, Sammelwerkzeug, Manipulationsmatrix, Regel R9

Alle Angaben stammen aus maschinellen Gate-Ergebnissen, sanitierter Evidenz,
deklarativen Manifesten sowie Commit- und Branchdaten. Rohlogs werden nicht
zitiert.

## §1 Lage

| Größe | Wert |
|---|---|
| Worktree | `git rev-parse --show-toplevel` |
| Branch | `spike/calendar-foundation-intel-2026-08-04` |
| Ausgangscommit (Blockstart) | `f3dd0f48b2896acc6df789f4ae775021a924cda8` |
| Normativer Commit, Position 1 | `d3f9337462aafc9be65498b4d49ed3748f001285` |
| Normativer Commit, Position 2 und Abnahmecommit | `5fe885a7dca7a1e7f9e82f26e24f0a7c41b1635a` |
| Geänderte Dateien seit Blockstart | 36 Dateien, 9081 Einfügungen, 183 Löschungen |
| `git diff --check` | ohne Befund |
| Blockmanifest | `config/gates/blocks/b0d-guard-hardening.json`, 63 Prüfungen |

## §2 Phasenergebnisse

Abnahmelauf gegen `5fe885a` bei sauberem Arbeitsbaum:

| Phase | Ergebnis | Prüfungen |
|---|---|---|
| `preflight` | `pass` | 12 |
| `targeted` | `pass` | 10 |
| `offline-final` | `pass` | 32 |
| `platform-live` | `pass` | 5 |
| `module-final` | `pass` | 4 |

Maschineller Gesamtstatus: **`pass`**. Keine Phase ist `not_applicable`, keine
Phase ist `blocked`, kein Ergebnis wurde umgedeutet.

Ergänzungslauf nach dem Schreiben der feststellenden Datensätze: `targeted`
`pass` (10), `offline-final` `pass` (32). Er ersetzt die gebundene Evidenz
nicht, sondern steht daneben.

Baseline: deklariert `7986bee`, nicht aufgelöst, **nicht verwendet**;
Ursachensignaturversion `cs-1`; Cachezustand `not_used`. Es gibt in diesem
Block kein `pass_with_baseline`. Die Baseline-Arbeitsbaum- und Cacheprüfung
läuft über `pf-baseline-commit` und die Baseline-Policy des Manifests; beide
sind `pass` beziehungsweise `cache_enabled=false`.

## §3 Merkmalsprüfung gegen den unmittelbaren Vorgänger

Vorgänger ist B0c (`config/gates/features/b0c-governance.lineage.json`), per
SHA-256 gebunden.

| Größe | Wert |
|---|---|
| erwartet | 166 |
| zugeordnet | 166 |
| geändert | 0 |
| fehlend | 0 |

Eigene Merkmale: Präfix `B0D-`, 43 erwartet, 43 nachgewiesen, 0 fehlend. Jedes
eigene Merkmal ist an eine Gate-Prüfung, einen Test oder eine wirklich
vorhandene Datei gebunden. Erhaltung der Vorgängerlinien aus `mf-preservation`:
`B0A1-` 24/24, `B0A2-` 38/38, `B0A3-` 14/14, `B0A4-` 35/35.

## §4 Prüfungen im Einzelnen

Strukturelle Signaturtests, Evidenz- und Canary-Tests sowie die Hook-Testmatrix
sind in diesem Block **nicht** als eigene Manifestprüfungen geführt, sondern
laufen innerhalb von `of-tooling-tests` über den vollständigen Baum
`tests/tooling`; diese Prüfung ist `pass`. Die Canary- und Rohlogprüfung des
Arbeitsbaums läuft zusätzlich eigenständig in `pf-worktree-state` und
`of-repo-guard`, beide `pass`. Das ist eine Aussage über die Abdeckung, nicht
über gleichwertige Einzelnachweise.

`of-historical-integrity` ist `pass`: für B0a-1 bis B0a-4, B0c und B0d ist die
gebundene Evidenz vollständig vorhanden, `evidence_absent=0` in allen sechs
Fällen.

## §5 Was dieser Block festgestellt hat

**Die Ausnahme entscheidet nicht mehr mit.** Drei Fragen sind getrennt: ob ein
Objekt lesbar ist, ob es hier gilt, ob es passt. Nur ein Kandidat erreicht eine
Entscheidung. Ein abgelaufenes oder versionsfremdes Objekt erzeugt ein Ergebnis,
das mit dem leeren Bereich byteidentisch ist — kein eigener Grund, kein
Nonce-Digest. Ein korruptes Objekt blockiert unverändert.

**Sammelwerkzeug.** `status`, `verify` und `plan-collect` lesen; `collect`
verschiebt. Dass die Sitzung nicht sammeln kann, ist kein Versprechen: jeder
Schreibaufruf des Moduls liegt in genau einer Funktion, diese verweigert vor
ihrem ersten Schreibvorgang ohne root, der Eigentümer-Wrapper verweigert
unabhängig davon, und ein Gate liest den Syntaxbaum und belegt, dass außerhalb
dieser Funktion kein Schreibaufruf existiert. Nie gelöscht, nie bearbeitet, nie
ein Kandidat angefasst, nie ein bereits eingesammeltes Objekt überschrieben.

**Ein korruptes Objekt wird nicht eingesammelt.** Es ist die einzige Art, die
noch jede Entscheidung blockiert; es einzusammeln hieße, eine Blockade zu
reparieren, die niemand angesehen hat.

**Manipulationsmatrix.** 23 Zeilen über einem wohlgeformten Objekt, jede mit
Manipulation, mechanischem Wirkungsnachweis und erwartetem Ausgang. Keine Zeile
ersetzt ein Literal, das heute zufällig in der Datei steht. Die Vollständigkeit
ist abgeleitet statt behauptet: jeder Korruptionscode wird aus dem Syntaxbaum
des Guards gelesen und braucht eine Zeile oder eine benannte Begründung, warum
keine Manipulation ihn erreicht. Drei haben eine solche Begründung.

**Regel R9, Einwirkung muss belegt sein.** Durchgesetzt über den Syntaxbaum: die
erste Zusicherung einer deklarierten Funktion muss die deklarierte
Wirkungszusicherung sein. Eine Zusicherung, die unter die Erwartung gerutscht
ist, fällt damit auch dann, wenn der Test weiter besteht.

**Die Aufzeichnung erreichte nichts.** `decide()` baute die Beobachtungen,
`entry.run()` nahm ein Verzeichnis entgegen — aber der Prozesseinstieg, den der
Bootstrap aufruft, hatte diesen Parameter nicht, und der Bootstrap benannte kein
Verzeichnis. Im installierten Guard war der ganze Pfad toter Code. Jetzt
verdrahtet, mit denselben Anhänge-Rechten wie das geschützte Protokoll.

**R6 zum zweiten Mal.** Der für `d3f9337` abgeleitete Paket-Hash war im Umlauf.
Das Paket hat sich seither geändert, also gehört dieser Wert nicht mehr zum
Kandidaten. Neu abgeleitet am tatsächlichen Abnahmecommit, zweimal unabhängig.
Die beiden Werte unterscheiden sich wirklich — Weiterreichen hätte dieselbe
Verweigerung erzeugt wie beim ersten Mal.

Korrekturvermerke: `config/gates/history/b0d-corrections.json`, drei Vermerke
(`B0D-N1` bis `B0D-N3`). Kein früherer Satz ist umgeschrieben.

## §6 Guard-Aktivierung

Der Block wurde gegen die tatsächlich aktive Guard-Version abgenommen: `1.2.0`,
Quellcommit `f3dd0f4`, Paket-Hash aus dem Commitobjekt neu abgeleitet und
bestätigt. Der Kandidat ist `1.3.0` und **nicht** aktiv.

| Größe | Wert |
|---|---|
| Kandidatencommit | `5fe885a7dca7a1e7f9e82f26e24f0a7c41b1635a` |
| Kandidatenversion | `1.3.0`, `guard-config-1` |
| `package_sha256` | `a775a30f4f0ce88b7ad2aff939222b650d5260b3d920f423755630e9cf212db4` |
| Ableitung | zweimal unabhängig aus dem Commitobjekt |
| Registriert als | `EXP-002-guard-package-b0d-acceptance` |

Kein Manifest übergibt `--expect-version` oder `--expect-hash`, die
`platform-live`-Modi arbeiten auf dem, was installiert ist, und die
Offline-Runner sind Unterprozesse, die der `PreToolUse`-Hook nie sieht. Die
Aktivierung ist damit **Folge** dieser Abnahme, nicht ihre Voraussetzung, und
ist eine Eigentümerhandlung nach Blockabschluss.

## §7 Ausdrückliche Bestätigungen

- kein Produktcode geändert — die 36 geänderten Pfade liegen vollständig in
  Werkzeug, Tests, Governance und Skripten, geprüft gegen den Blockstart,
- kein Live-Lauf gegen ein produktives System, keine Provider- oder
  Netzbeteiligung,
- kein `sudo` ausgeführt, keine Installation verändert, kein Ausnahmeobjekt
  verschoben, bearbeitet oder gelöscht,
- kein Merge, kein Rebase, kein Cherry-pick, kein Tag, kein Release,
- kein Force-Push, kein automatischer Push,
- keine DEC- oder ADR-Nummer vergeben, keine reserviert,
- `CLAUDE.md` unverändert,
- kein Folgeblock begonnen.

Pushstatus: **`not_performed_owner_action`**.

## §8 Offene Befunde

1. **Claude-Code-Anwendung als offene Vertrauenswurzel** — unverändert.
2. **Schutzprotokoll nach vorn fälschbar** — unverändert. Der neue
   Beobachtungsbereich hat dieselbe Eigenschaft und das Vertrauensmodell sagt
   das ausdrücklich.
3. **Backstop-Ebene überschätzt bewusst** — unverändert; in diesem Block erneut
   praktisch bestätigt.
4. **Selbstaussperrung bei ungültiger Guard-Konfiguration** — unverändert.
5. **Das Sammelwerkzeug verweigert gegen den aktiven Guard 1.2.0.** Diese
   Version hat keine Qualifikationsschicht, und das Werkzeug beschreibt einen
   Guard nicht in Worten, die er nicht hat. Jede Gate-Prüfung nutzt die
   Repository-Fassung und nennt diese Quelle in jedem Bericht. Löst sich mit der
   Aktivierung.
6. **Die Aufzeichnung beginnt mit der Aktivierung.** Bis dahin existiert der
   Beobachtungsbereich nicht und die Aufzeichnung ist ein No-op — dokumentiertes
   Verhalten, kein Fehlschlag.
7. **`mf-evidence` und `mf-phase-results` aggregierten im Abnahmelauf eine leere
   Menge**, weil die Evidenz dieses Blocks erst im feststellenden Commit
   danach liegt. Für einen späteren Wiederholungslauf sind sie aussagekräftig,
   für diesen nicht. Das ist kein `fail` und wird auch nicht als Nachweis
   geführt.
8. **Die Produktschutz-Deklaration ist unverändert wirkungsarm.**
   `allowed_paths` ist ein einzelner Platzhalter, weil der geprüfte Bereich am
   Linienursprung beginnt und dort bereits Produktpfade berührt sind. Die
   Aussage „kein Produktcode geändert“ stützt sich auf das Blockdelta, nicht auf
   diese Deklaration.
9. **Registerdaten existieren weiterhin nicht.** Unverändert aus B0c.

## §9 Für den nächsten Block

1. **Testhärtungsschritt** (unmittelbar nach B0d): Durchsicht des gesamten
   Testbestands nach Tests derselben Bauart wie der in `B0D-N1` beschriebene,
   Aufnahme jedes Fundes in `config/governance/effect-evidence.json`. Bis dahin
   ist über nicht gelistete Tests nichts ausgesagt.
2. **Registrierung als Governance-Entscheidungen**, sobald das
   Reservierungsregister läuft: R1 bis R9, die Zwei-Test-Regel,
   Bericht-als-Folge und die Eigentümergrenzen.
3. **Oberflächenparität als allgemeine Fähigkeit**, mit den Instanzen Kalender
   und Kontakte.
4. **Mechanische Architekturklassifikation der fünf offenen K1-Gates**
   (`K1-O01`, `K1-O02`, `K1-O03`, `K1-O05`, `K1-O06`). In B0c nicht erstellt, in
   B0d ebenfalls nicht, und hier nicht vorweggenommen.

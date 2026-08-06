---
Status: normativ (B0a-4 Abschluss-Handoff für B0b)
Erzeugt aus: maschinelle Gate-Ergebnisse, sanitierte Evidenz, Git-Daten, deklarative Manifeste, reale Eigentümer- und Rechteprüfungen
Zielbranch: spike/calendar-foundation-intel-2026-08-04
Ersetzt: die B0a-3-Fassung dieses Handoffs (historisch über `a093687` unverändert nachvollziehbar)
---

# B0b-Handoff — verbindlicher Ausgangszustand

Dieses Handoff liefert B0b den Ausgangszustand ohne erneute Rekonstruktion.
Es nimmt den B0b-Auftrag **nicht** vorweg und trifft keine fachliche
Entscheidung.

## §1 Git-Zustand

| Größe | Wert |
|---|---|
| Kalenderbranch | `spike/calendar-foundation-intel-2026-08-04` |
| Ausgangscommit B0a-4 | `a0936877254c092bc75314b8078dedeb1deccc7a` |
| B0a-4-Commit 1 | `02b775ecc12bf3d1b62ca20fe9cb1b18a2f2ea3a` — fail-closed Guard, worktree-unabhängiger Bootstrap |
| B0a-4-Commit 2 | `834f08ac1bfa21f1892483174a055e38077bfa5b` — Vor-Aktivierungs-Korrektur, root-eigener Interpreter |
| B0a-4-Commit 3 | der Commit, der diese Datei trägt — Live-Evidenz und Handoff |
| Remote-Stand vor Eigentümer-Push | `a0936877254c092bc75314b8078dedeb1deccc7a` |
| Arbeitsbaum bei Abschluss | sauber |
| Amend innerhalb B0a-4 | keiner |
| Rebase, Squash, Cherry-pick | keiner |
| Pushstatus | `not_performed_owner_action` |

`a093687` ist unverändert: Tree `fccc84649735b147dd3e7914ecb8921710c5daf3`,
Eltern `8e6e206` und `4e47144`, Autor- und Committerdatum unverändert. Die
Bindung steht maschinenlesbar in
`config/gates/history/b0a-4-commit-plan.json` und wird von
`of-base-commit-unchanged` bei jedem Lauf geprüft.

**Abweichung vom deklarierten Commitplan.** Die Vorprüfung deklarierte zwei
Commits. Die vor der Eigentümeraktivierung verpflichtende Validierung fand
einen Sicherheitsdefekt des ersten Kandidaten (§2.6). Er musste in einem
Commit **vor** der Aktivierung behoben werden, und Amend ist gesperrt.
Daraus wurden drei Commits. Grund, Art und Bewertung stehen im Feld
`plan_deviation` desselben Manifests. Der dritte Commit ist kein reiner
Bindungscommit, sondern der planmäßige Evidenz- und Handoff-Commit, der um
eine Position verschoben wurde.

## §2 Guard-Bootstrap

### §2.1 Gewählte Architektur

Eigentümerkontrollierte, root-eigene Installation außerhalb jedes Worktrees,
registriert über die Policy-Stufe von Claude Code. Vollständige Bewertung in
`docs/governance/b0a-4-guard-architecture.md`.

| Größe | Wert |
|---|---|
| Hook-Registrierung | `/Library/Application Support/ClaudeCode/managed-settings.json`, `root:wheel`, `0644` |
| Registrierter Befehl | `/usr/local/jarvis-guard/bootstrap.sh` |
| Externer Guard-Pfad | `/usr/local/jarvis-guard` |
| Guard-Version | `1.0.0` |
| Quellcommit | `834f08ac1bfa21f1892483174a055e38077bfa5b` |
| Aktiver Paket-Hash | `30a41d822956ed1441f581febbd55883cd58c6875ebc3350ad0dce5edcd0f322` |
| Konfigurationsschema | `guard-config-1` |
| Interpreter | `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9` |
| Eigentümer und Rechte | Wurzel `root:wheel 0755`, `active.json` `0444`, Paketdateien `0444`, `bootstrap.sh` `0755` |
| Aktivierungszeitpunkt | `2026-08-06T11:29:15Z`, durch Lukas, mit Kennworteingabe |

### §2.2 Verworfene Varianten

| Variante | Grund der Verwerfung |
|---|---|
| Gemeinsames Git-Verzeichnis | Claude Code liest dort keine Hook-Registrierung; zusätzlich bleibt `.git` sitzungsschreibbar, ein geschütztes Unterverzeichnis ist daher durch Umbenennen aushebelbar, und `core.hooksPath` sowie Git-Aliase sind umleitbar. |
| Benutzerkonfiguration `~/.claude/settings.json` | Von der bewachten Sitzung anlegbar, änderbar und löschbar. Außerhalb des Repositorys zu liegen macht eine Konfiguration nicht eigentümerkontrolliert. |
| Installation unter `/usr/local/lib` | Auf diesem Rechner `lukasklunder:admin` und gruppenschreibbar; ein Schreibtest der Sitzung war erfolgreich. |

### §2.3 Nachweis der Nichtveränderbarkeit

Gate `pl-tamper`, real unter den Rechten der bewachten Sitzung gefahren:

| Komponente | Ergebnis |
|---|---|
| Installationswurzel | nicht schreibbar |
| aktives Paket und Regelkonfiguration | nicht schreibbar |
| `active.json` (Hash- und Versionsbindung) | nicht schreibbar |
| `bootstrap.sh` und `bootstrap.py` | nicht schreibbar |
| Policy-Verzeichnis und Hook-Registrierung | nicht schreibbar |
| Ausnahmeverzeichnis `pending` | nicht schreibbar |
| Schutzprotokoll | anhängbar, **nicht** kürzbar und nicht überschreibbar |
| Ausnahmemarker `spent` | setzbar, **nicht** entfernbar |

Grundlage: root-Eigentum aller Komponenten, root-Eigentum jedes
Elternverzeichnisses bis `/`, ACLs für Protokoll und Verbrauchsmarker, und
`sudo` ohne Kennwort scheitert in der Sitzung.

### §2.4 Live-Gate-Evidenz

| Gate | Ergebnis |
|---|---|
| `pl-active-guard` | pass — Version, Hash, Quellcommit, Eigentümer, Modi, Registrierung, Interpreter |
| `pl-live-calendar` | pass — 16 verbotene Formen blockiert, 3 erlaubte unberührt, leeres und manipuliertes `CLAUDE_PROJECT_DIR` ohne Wirkung |
| `pl-live-plain-worktree` | pass — identischer Schutz in einem Worktree ohne `tools/gates` |
| `pl-tamper` | pass — §2.3 |

### §2.5 Eigentümerausnahme — Live-Verhalten

Vier Nachweise am aktiven Guard, alle gegen zwei leere Wegwerfverzeichnisse
außerhalb jedes Repositorys:

| Fall | Ergebnis |
|---|---|
| Variante des freigegebenen Befehls (abweichender kanonischer Text) | blockiert, keine Ausnahme zugeordnet |
| exakter Befehl | einmal freigegeben, Ereignis `exception_consumed`, Wirkung eingetreten |
| zweiter Versuch desselben Befehls | blockiert, Ausnahme gefunden, aber verbraucht |
| abgelaufene Ausnahme | blockiert, Ausnahme gefunden, aber abgelaufen |

Zusätzlich belegt: der Helfer erzeugt ohne ausdrückliches `--confirm` nichts,
und er zeigt weder Nonce noch Integritätsdigest an. Das Protokoll führt
ausschließlich einen gekürzten Nonce-Digest, nie den Nonce selbst.

### §2.6 Vor der Aktivierung gefundener und behobener Defekt

`/usr/bin/python3` ist auf diesem Rechner nur ein Stub und löst nach
`/Applications/Xcode.app` auf. Dieses Bündel gehört dem Sitzungsbenutzer und
ist von ihm beschreibbar. Der erste Kandidat hätte damit einen
sitzungsschreibbaren Interpreter in die Vertrauenskette gestellt und wegen
seiner Pfadgleichheitsprüfung zusätzlich nach der Aktivierung jeden
Toolaufruf blockiert. Behoben in Commit 2: root-eigener
Command-Line-Tools-Interpreter, und der Bootstrap prüft nun die **gesamte
Ahnenkette** von Installationswurzel, deklariertem und tatsächlich laufendem
Interpreter. Deklariert als Regeländerung `RC-006`.

## §3 Historische Abnahme und aktuelle Erhaltung

Beides ist getrennt und wird nicht vermischt.

### §3.1 Historische Abnahme

Gebunden an Commit, unveränderliche Referenz-SHAs, Manifest- und
Gate-Version, Umgebungsmerkmale sowie Hashes der erzeugten Evidenz. Diese
Manifeste werden **nicht** erneut gegen die heutige Branchspitze ausgeführt;
geprüft werden nur Vorhandensein, Hashintegrität, korrekte Bindung und
unveränderte Aussage (`of-historical-integrity`).

| Block | Abnahmecommit | Zustand |
|---|---|---|
| B0a-1 | `5b6d1ae` | historisch abgenommen, Evidenz hashvalide |
| B0a-2 | `4e47144` | historisch abgenommen, Evidenz hashvalide |
| B0a-3 | `a093687` | historisch abgenommen, Evidenz hashvalide |

Manifeste: `config/gates/history/*.acceptance.json`.

Nicht mehr behauptet wird, jedes alte linienabhängige Abnahmemanifest sei
gegen den heutigen Branchzustand erneut vollständig grün.

### §3.2 Aktuelle Erhaltung

`config/gates/preservation/calendar-line.preservation.json`, linienunabhängig
formuliert: keine Branch-Topologie, keine veränderliche Remote-Branchspitze,
keine branchspezifische Pfad-Allowlist. Geprüft auf dem jeweils aktuellen
HEAD (`of-preservation`, `mf-preservation`).

| Größe | Soll | Ist |
|---|---|---|
| Erhaltung B0a-1-Merkmale | 24 | 24 |
| Erhaltung B0a-2-Merkmale | 38 | 38 |
| Erhaltung B0a-3-Merkmale | 14 | 14 |
| B0a-4-Eigenmerkmale | 35 | 35 |

Zusätzlich geprüfte Invarianten: fünf Phasen und fünf Ergebnisse der
Gate-Engine, öffentliche Gate-Schnittstelle, Obermenge der Guard-Denycodes
einschließlich `git_commit_amend`, fail-closed Ausgänge beider
Hook-Einstiege, genau eine Guard-Implementierung, kanonische
Lieferreihenfolge, unaufgelöster Ambient-Platzhalter, pfadgenaue
Allgemeinheits-Allowlist, PII-Canaries und gitignorierter Laufzeitbereich.

## §4 B0a-3-Erratum

`docs/governance/b0a-3-errata.md` hält als Nachtrag fest: die Reflog-Kette
`d2bce8f → b872f91 → ad84559 → a093687`, drei lokale `commit --amend`, keine
Veröffentlichung der drei Zwischenstände, finaler Remote-Stand `a093687`,
genau ein Merge-Commit im finalen Graphen, den Unterschied zwischen
Graphform und Entstehungsgeschichte, die damals fehlende Amend-Sperre, das
fail-open-Verhalten bei fehlendem `tools/gates` und den fehlenden
durchgehenden Wirksamkeitsnachweis während B0a-3. Keine alte Evidenz wurde
verändert.

## §5 K1-Ausgangszustand

Neu berechnet gegen den B0a-4-HEAD. Grundlage ist
`docs/personal-jarvis/modules/calendar.md` § 7 und § 8; dieses Dokument ist
zwischen `a093687` und dem heutigen HEAD **bytegleich** (Blob
`fa9f23847433f2c48d5026aa8892a3e3b898fbc3`), und B0a-4 hat keinen
Produktpfad berührt. Die Verteilung ist damit bestätigt, nicht übernommen.

Verteilung: **acht erfüllt, null gegen Baseline akzeptiert, neun offen.**

### §5.1 Erfüllt (mit Evidenzreferenz)

| K1-Gate | Evidenzreferenz |
|---|---|
| Python-Testlauf `tests/personal` | `modules/calendar.md` § 7 — 1185 grün, 85 übersprungen, 1 rot (siehe § 5.3) |
| Kalender-Suite (Sync-Vertrag 27, Grenzen 23) | `modules/calendar.md` § 7 — 50 grün |
| Frontend `vitest run` | `modules/calendar.md` § 7 — 216 grün, davon 65 Kalender |
| `tsc --noEmit` | `modules/calendar.md` § 7 — grün |
| `ruff` auf neuem Code | `modules/calendar.md` § 7 — grün |
| Sidecar-Bau (`minos 12.3`, keine Schreibselektoren im Binary) | `modules/calendar.md` § 7 — grün |
| Kalenderfreier Handshake gegen das echte Binary | `modules/calendar.md` § 7 — `ready`, `ping`, `caps`, `shutdown` grün |
| Fail-closed ohne Berechtigung | `modules/calendar.md` § 7 — `outcome: failed`, kein Datensatz, kein Tombstone |

### §5.2 Gegen Baseline akzeptiert

Derzeit **keines**. Es ist keine maschinenlesbar gebundene Baseline-Ausnahme
für ein K1-Gate hinterlegt. Ein offenes Gate wird nicht umetikettiert.

### §5.3 Offen (mit Blockierungsgrund und erforderlicher B0b-Arbeit)

| K1-Gate | Blockierungsgrund | Erforderliche B0b-Arbeit |
|---|---|---|
| Echter Lesedurchlauf aus der gepackten App | Aus dem Terminal gestartet ist der verantwortliche Prozess das Terminal; der Beweis sagt nichts über Jarvis aus und trüge dem Terminal eine dauerhafte Kalenderberechtigung ein. Erforderlich auf **beiden** Architekturen. | Durchlauf aus der gepackten Anwendung heraus belegen |
| ARM64 vollständig | Keine Zeile des Kalenderblocks gilt für Apple Silicon (`DEC-042`); „unsigniertes Kind erbt den Zugriff" ist ein reiner Intel-Befund. | Nachweis auf Apple Silicon |
| TCC-Persistenzmatrix | Rebuild, Versions-Bump, Verschieben und Quarantäne sind unbelegt. | Persistenzverhalten messen |
| Große Bestände | Laufzeit, Speicher und Fensterwahl bei tausenden Terminen sind ungemessen. | Messung an großem Bestand |
| Teilnehmer im Echtbetrieb | Modell gebaut und getestet, im gemessenen Fenster gab es null Teilnehmer. | Beobachtung mit echten Teilnehmern |
| Apple-Paritätsvertrag P-1…P-15 | Erst teilweise erfüllt, nirgends visuell gegen die M2-Referenz verglichen; offen insbesondere P-7, P-9, P-12 und P-13. | Paritätsvergleich gegen die Referenz |
| Schreiben | Eigener Auftrag; erbt `ADR-0025`/`ADR-0026` unverändert. | Eigener Schreibauftrag |
| Zweiter Datenpfad `gcalendar.py` | Unberührt; Ablöseplan steht in Baseline § 5. | Ablösung nach Baseline § 5 |
| Vorbestehend roter Test `test_dec_052_ist_registriert` | Prüft eine Zählung im Entscheidungsregister und schlägt auch ohne den Kalenderblock fehl. Vorbestehend, nicht durch B0a-3 oder B0a-4 verursacht. | Ursache im Entscheidungsregister klären |

Keine Lösung wird hier vorweggenommen.

## §6 Werkzeugstand

Die B0a-Werkzeugkette liegt vollständig auf der Kalenderlinie:
`scripts/gate.sh` mit fünf Phasen und fünf Ergebnissen, Baseline-Engine gegen
`7986bee`, allowlistbasierte Evidenz, PII-Canaries, Guard-Basis, Governance-
und Allgemeinheitsprüfungen sowie die Projektskills `gate` und
`handoff-report`. Es gibt **kein** zweites Gate-System.

Neu in B0a-4: genau eine Guard-Implementierung in `tools/guard`, der
Paketbau in `tools/guardpkg`, die Eigentümerhelfer
`scripts/guard-install.sh` und `scripts/guard-exception.sh`, die
Regeländerungs-Metagates in `config/guard/` und die Trennung von
historischer Abnahme (`config/gates/history/`) und aktueller Erhaltung
(`config/gates/preservation/`).

Blockmanifeste: `b0a-1-tooling`, `b0a-2-governance`, `b0a-3-integration`,
`b0a-4-guard`, `tooling-merge-readiness`.

Der repositoryseitige Hook `.claude/hooks/pretooluse_guard.sh` ist
ausdrücklich **nicht** die Vertrauensgrenze. Er stellt sich zurück, sobald
der eigentümerinstallierte Guard installiert **und** registriert ist, weil er
dieselben Regeln anwendet, aber die Eigentümerausnahmen nicht kennt und sonst
eine Eigentümerentscheidung überstimmen würde (`RC-007`). Ohne aktiven
externen Guard entscheidet er unverändert weiter.

## §7 Offene Befunde

Diese Punkte sind belegt und bleiben offen. Sie sind keine Mängel der
Umsetzung, sondern Grenzen, die benannt gehören.

1. **Die Claude-Code-Anwendung selbst ist benutzerschreibbar.** Sie liegt
   unter `~/Library/Application Support/Claude/claude-code/` und gehört dem
   Sitzungsbenutzer. Wer die Anwendung ersetzt, umgeht jede Konfiguration,
   die diese Anwendung liest — auch die Policy-Stufe. Das ist die
   Vertrauenswurzel jeder hookbasierten Absicherung und durch keinen
   Bestandteil dieses Blocks schließbar.
2. **Die Sitzung läuft unter einem Administrator-Konto.** Mit dem Kennwort
   des Eigentümers ist jede Grenze aus §2 aufhebbar. Die Grenze lautet
   „erfordert eine interaktive Eigentümerauthentisierung", nicht „technisch
   unmöglich".
3. **Das Schutzprotokoll ist nach vorn fälschungsoffen.** Einträge sind weder
   entfernbar noch überschreibbar, aber die Sitzung kann eigene Einträge
   anhängen. Eine Signatur änderte nichts, weil jeder Schlüssel, den der
   Wächter lesen kann, auch der Sitzung zugänglich ist.
4. **Der Protokoll-Scrubber greift zu kurz.** Er ersetzt `/Users/<name>` und
   `/home/<name>`, nicht aber Benutzernamen, die als Namensbestandteil eines
   Verzeichnisses auftreten (etwa in Claude-Code-Sitzungspfaden). Das
   Protokoll ist root-eigen und wird nie committet, erreicht also keine
   commitfähige Evidenz. Behebung erfordert eine neue Guard-Version und damit
   eine erneute Eigentümeraktivierung.
5. **Die Backstop-Ebene überschätzt bewusst.** Sie prüft den Rohtext
   einschließlich Heredoc-Inhalten. Ein Dokument, das einen verbotenen Befehl
   nur erwähnt, wird deshalb blockiert. Das ist die sichere Richtung und
   entspricht dem bisherigen Verhalten; eine Entschärfung wäre eine
   Verringerung der Verstoßmenge und bedürfte einer Eigentümerentscheidung.
6. **Mehrdeutige Git-Operationen bleiben ungesperrt.** `cherry-pick`,
   `merge --squash`, `commit-tree`, `reset --soft/--mixed/--keep/--merge`,
   `branch -d/-D`, `tag -f`, `gc`/`prune` und `checkout --orphan` sind in
   `config/guard/history-rewrite-matrix.json` als offene Befunde geführt. Für
   sie wurde bewusst keine neue Eigentümerregel erfunden.

## §8 Was B0b vorfindet

- B0b startet auf dem B0a-4-HEAD, nicht auf `a093687`.
- Der externe Guard ist **aktiv**.
- Die aktive Version ist hashgebunden an
  `30a41d822956ed1441f581febbd55883cd58c6875ebc3350ad0dce5edcd0f322` aus
  Quellcommit `834f08a`.
- Ein Worktree ohne integriertes Tooling bleibt geschützt; das ist live
  belegt.
- Vor Beginn von B0b ist **keine** Eigentümeraktion mehr offen außer dem
  abschließenden Push.

B0a-4 hat keine fachliche Entscheidung getroffen, keinen Produktcode
funktional geändert, kein Kalender-K1 begonnen, keine Kontakte-Arbeit
geleistet, keine neue DEC- oder ADR-Datei erzeugt, keinen Tag und kein
Release erzeugt und keinen Push ausgeführt.

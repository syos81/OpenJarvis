# Jarvis – Grundregeln

Jarvis ist Lukas' persönlicher KI-Assistent. Diese Datei definiert, wie Claude
sich in diesem Projekt verhält. Sie stammt aus dem bisherigen Jarvis-Repository
und ist für OpenJarvis und den Werkzeugblock B0a-1 ergänzt worden.

## Identität

- Antworte direkt, präzise und ohne unnötige Ausschweifungen.
- Sprich Lukas mit Namen an, wenn es den Kontext verbessert.
- Sprache: Deutsch, außer Lukas wechselt explizit ins Englische.

## Harte Grenzen – niemals ohne explizite Bestätigung

- Keine E-Mails versenden.
- Keine Termine oder Kalendereinträge erstellen oder löschen.
- Keine Dateien außerhalb dieses Projektordners löschen oder überschreiben.
- Keine Zahlungen, Überweisungen oder Vertragsaktionen auslösen.
- Keine Kundendaten, persönlichen Dokumente oder Zugangsdaten automatisch
  verarbeiten.
- Keine externen Accounts verbinden oder authentifizieren.
- Keine produktiven Systeme (E-Mail, CRM, Bank) ohne expliziten Trigger
  berühren.

## Standard-Verhalten

- Vor jeder destruktiven oder irreversiblen Aktion kurz fragen und bestätigen
  lassen.
- Neue Funktionen immer erst lokal und im Trockenlauf testen, bevor sie auf
  echte Systeme zugreifen.
- Fehler transparent melden – keine stillen Fehlschläge.
- Keine Daten nach außen senden, die nicht explizit freigegeben wurden.

## Arbeitsbereich

- Den aktuellen Worktree immer selbst ermitteln:
  `git rev-parse --show-toplevel`. Nie einen Repositorypfad fest codieren und
  nie einen früher gemerkten absoluten Pfad wiederverwenden.
- Es gibt mehrere Worktrees desselben Repositorys. Änderungen gehören
  ausschließlich in den aktiven Worktree.
- Fremde Worktrees und fremde Arbeitskopien werden nie verändert. Der
  repositorylokale `PreToolUse`-Hook eskaliert solche Ziele an Lukas; eine
  Eskalation wird nicht umgangen.
- In größeren, sinnvoll abgeschlossenen Arbeitsblöcken arbeiten statt in
  vielen Kleinstschritten.

## Gates, Ergebnisse und Baseline

- Prüfungen laufen ausschließlich über die öffentliche Schnittstelle
  `scripts/gate.sh --block <block-id> --phase <phase>`.
- Verbindliche Phasen: `preflight`, `targeted`, `offline-final`,
  `platform-live`, `module-final`. Während der Arbeit gezielt prüfen
  (`targeted`), am Blockende die vollständigen relevanten Gates fahren.
- Verbindliche Ergebnisse: `pass`, `pass_with_baseline`, `fail`, `blocked`,
  `not_applicable`. Autoritativ ist immer das Enum im maschinellen Bericht.
- Maschinelle Ergebnisse werden wörtlich respektiert. Keine Umdeutung, keine
  Abschwächung, kein grüner Abschluss bei `fail` oder `blocked`, kein manueller
  Testlauf als Ersatz für ein fehlendes Gate-Ergebnis.
- `pass_with_baseline` entsteht ausschließlich aus der Baseline-Engine gegen
  den Commit `7986bee` mit identischer struktureller Ursachensignatur – nie aus
  Textähnlichkeit, Exitcode oder einer Behauptung.
- `not_applicable` nur aus einer deklarativen Manifestregel, nie weil eine
  Prüfung unbequem oder unfertig ist. Eine fehlende Voraussetzung ist
  `blocked`.

## Evidenz und Datenschutz

- Rohlogs liegen ausschließlich im gitignorierten Laufzeitbereich
  `.gate-runtime/`. Sie werden nicht committed, nicht zitiert und nicht in
  Antworten oder Berichte kopiert.
- Nach außen geht nur allowlistbasierte, sanitierte Evidenz. Kein Freitextfeld
  ersetzt ein maschinelles Feld.
- Keine echten Kontakt-, Kalender-, Mail-, Bank- oder Mieterdaten in Tests,
  Fixtures oder Berichten – ausschließlich synthetische Werte.

## Allgemeinheit und Modullandkarte

- Capability-Verträge sind providerneutral und fachbereichsbezogen; es gibt
  keine Mega-Schnittstelle.
- Organisationen, Workspaces, Rollen, Fachbereiche, Tags und Vorgangstypen
  sind Konfigurations- oder Datenwerte, niemals hart codierte Fachlogik.
- Kein Schema, Enum, Zustand, Feld, Routensegment, Typname oder Modulname
  enthält eine konkrete Organisation.
- Providerbegriffe stehen ausschließlich an der Adaptergrenze: Adapter,
  Providermanifeste, Capability-Implementierungen und deren Tests. Es gibt
  keine pauschale globale Allowlist, jede Freigabe ist pfadgenau.
- Allgemeinheit gilt ab dem ersten realisierten Fall als Vertrags- und
  Konfigurationsregel. Eine gemeinsame Engine entsteht erst beim zweiten
  realen, fachlich unterschiedlichen Fall aus mindestens zwei belegten
  Implementierungen. Keine spekulative Plattform vorab.
- Fachbegriffe eines echten kanonischen Bestands bleiben zulässig;
  Allgemeinheit bedeutet nicht Fachbegriffslosigkeit.
- Verbindlich ist genau eine kanonische Liefer- und Fachmodulreihenfolge in
  `config/governance/delivery-order.json` mit
  `docs/governance/b0a-2-delivery-order.md` als Darstellung. Lieferposition und
  Fachmodulnummer sind getrennte Größen und werden nie verwechselt.
- Der Ambient-Platzhalter `{{DEC_ID_AMBIENT_INTERACTION_V1}}` bleibt
  unverändert, bis die Doppelvergaben integriert aufgelöst sind. Er wird weder
  berechnet noch reserviert noch durch eine bestehende Entscheidung ersetzt.

## Entscheidungen, IDs und Kollisionen

- Jeder normative DEC- oder ADR-Verweis nennt vollständige ID, Linie
  einschließlich belegtem Stand und exakten Titel. Eine bloße Nummer ist im
  Fließtext unzulässig.
- Entscheidungstitel werden wörtlich aus Register oder Primärtext übernommen,
  nie aus einer Beschreibung erraten.
- Keine eigenmächtige Vergabe neuer DEC- oder ADR-Nummern.
- Bekannte Doppelvergaben werden dokumentiert, nicht bereinigt: keine
  Umnummerierung, kein stilles Löschen einer Seite, keine Erklärung einer Linie
  zur allein gültigen Belegung.
- Bis zur integrierten Auflösung entsteht keine neue ADR-Datei und keine
  Reservierung.

## Versionierte Projektregeln

- Versioniert werden ausschließlich `CLAUDE.md`, `.claude/settings.json`,
  `.claude/hooks/**` und `.claude/skills/**`.
- Alles andere unter `.claude/` bleibt ignoriert, insbesondere
  `.claude/settings.local.json`, lokale Zustände, Caches, Rohlogs, temporäre
  Evidenz und rechnerbezogene Konfiguration.
- Die `.gitignore`-Ausnahmen sind pfadgenau. Eine pauschale Freigabe von
  `.claude/**` ist unzulässig.
- In den freigegebenen Dateien stehen keine Zugangsdaten, privaten Schlüssel,
  Tokens, eingebetteten Anmeldedaten und keine rechnerabhängigen absoluten
  Pfade. Projektpfade werden relativ zur Repository-Wurzel aus
  `git rev-parse --show-toplevel` verarbeitet.

## Abschluss und Handoff

- Ein Handoff-Bericht entsteht nur über den Projektskill `handoff-report` und
  nur aus überprüfbaren Quellen: maschinelle Gate-Ergebnisse, sanitierte
  Evidenz, Git-Status und -Diff, Commit- und Branchdaten, deklarative
  Manifeste.
- Vor jedem Abschluss läuft die Merkmalsvollständigkeitsprüfung gegen die
  Merkmalsliste des unmittelbaren Vorgängers. Ein fehlendes Pflichtmerkmal ist
  `fail`; der Block gilt dann nicht als abgeschlossen.
- Jede konsolidierte Fassung eines Prompts, Plans, Registers, Handoffs oder
  anderen normativen Artefakts durchläuft diesen Merkmalsvergleich gegen den
  unmittelbaren Vorgänger. Ein bloßer Gesamttext- oder Längenvergleich genügt
  nicht.
- Abschlussberichte sind kurz und deltaorientiert: was sich geändert hat,
  welche Phasen mit welchem Ergebnis liefen, welche echten Blocker bleiben.

## Commit und Push

- Jeder Arbeitsblock endet für Claude und andere Agenten nach dem erfolgreichen
  lokalen Commit. Pushes sind ausschließlich Eigentümerhandlungen außerhalb des
  Blocks. Ein Agent darf keinen Push ausführen, dafür keinen `ask`- oder
  Freigabepfad aufrufen und die Push-Sperre weder verändern noch über einen
  alternativen Prozess, Client, Hook, Alias, Unterprozess oder sonstigen Umweg
  umgehen. Als Pushanweisung darf ausschließlich ein einzelner, exakter
  manueller Befehl für den aktuellen Zielbranch ausgegeben werden. Das
  Ausbleiben des Eigentümer-Pushes macht einen ansonsten vollständig
  bestandenen lokalen Block nicht zu `fail` oder `blocked`.
- Der Pushstatus eines lokal abgeschlossenen Blocks lautet
  `not_performed_owner_action`.
- Kein Force-Push, kein Push auf einen Produktbranch, kein Merge, kein Rebase,
  kein Cherry-pick, kein Tag und kein Release durch einen Agenten.

## Agenten-Philosophie

Jarvis besteht aus spezialisierten Agenten, die unabhängig voneinander
arbeiten. Jeder Agent hat seinen eigenen Scope – er darf nur das tun, was in
seiner Agenten-Datei definiert ist. Kein Agent überschreitet seinen Bereich.
Der Agentenbestand wird im Assistenz-Repository gepflegt und hier nicht
dupliziert.

## Projekt-Skills

| Skill | Datei | Zweck |
|---|---|---|
| `gate` | `.claude/skills/gate/SKILL.md` | Gates über die öffentliche Schnittstelle fahren |
| `handoff-report` | `.claude/skills/handoff-report/SKILL.md` | Abschlussbericht aus überprüfbaren Quellen |

## Erweiterbarkeit

- Neue Fähigkeiten entstehen als neue Skill- oder Agenten-Dateien unter
  `.claude/`, nicht als zweite parallele Implementierung.
- Neue Berechtigungen werden explizit in `.claude/settings.json` eingetragen.
  Die harten Deny-Regeln (`git push`, `git reset --hard`, `git rebase`,
  `git clean`, `git stash drop`, `rm -rf`, Lesen von `.env`-Dateien) bleiben
  bestehen und werden nicht dauerhaft gelockert.
- Alle Änderungen an diesen Grundregeln erfordern Lukas' ausdrückliche
  Zustimmung.

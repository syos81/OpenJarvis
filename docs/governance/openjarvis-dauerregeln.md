# OpenJarvis — Dauerregeln V2

Stand: Eigentümervereinfachung 2026-08-11

## Ziel

OpenJarvis wird so schnell wie möglich zu einem tatsächlich nutzbaren
persönlichen Jarvis.

Sicherheit und mechanische Wahrheit bleiben hart. Prozesszeremonie ohne
konkrete Schutzwirkung entfällt.

## §1 Risikoprinzip

Prüfaufwand richtet sich nach dem realen Schadenspotenzial der Änderung.

Je größer die mögliche Fremdwirkung oder der mögliche Datenverlust, desto
stärker die Sicherung.

UI-, lokale Logik- und Fixture-Arbeit erhalten keine Produktionszeremonie.

## §2 Zwei Arbeitsspuren

Es dürfen parallel existieren:

**A. Risk Lane**

Für Arbeit mit mindestens einem dieser Merkmale:

- produktive oder externe Datenmutation,
- Delete,
- produktive Migration,
- reale Credentials,
- TCC,
- Signing/Release,
- globale Systemänderung,
- anderer schwer rückholbarer externer Side Effect.

**B. Safe Product Lane**

Für isolierte Produktarbeit ohne diese Wirkungen, beispielsweise:

- UI,
- Command Bar,
- Planner-Logik,
- Operator-Planung ohne Execute,
- Memory/Spaces mit disposable Testdaten,
- Context Engine,
- Injection-Erkennung,
- lokale Suche.

Eine Safe Lane darf eine laufende Risk Lane nicht an denselben produktiven
Daten, Systemzuständen oder konfliktträchtigen Arbeitsdateien koppeln.

## §3 Schutz vor Realschaden

Bei produktiven oder externen UPDATE- oder DELETE-Operationen:

- Ziel unmittelbar vor Execute erneut lesen.
- aktuellen Zustand gegen den genehmigten Zustand beziehungsweise
  Fingerprint prüfen.
- bei Abweichung fail-closed abbrechen.

Bei riskanten Live-Abnahmen:

- nur ausdrücklich für den Abnahmescope zugelassene Ziele mutieren.
- bestehende private Daten nicht als Testziel verwenden, solange ihre
  sichere Mutation nicht selbst Gegenstand und positiv bewiesen ist.

Diese Einschränkung ist eine Abnahme-Sicherheitsregel und keine allgemeine
Produktregel. Produktiv darf Jarvis später vorhandene Objekte bearbeiten,
wenn der jeweilige Produktionsvertrag dafür positiv bewiesen ist.

Bei Delete-Nachweisen:

- erfolgreicher Readpfad muss positiv belegt sein.
- zusätzlich zum fehlenden Ziel muss mindestens eine gebundene positive
  Readkontrolle vorhanden sein.

Vor destruktiven Tests oder Migrationen auf nicht-disposable Daten:

- brauchbares Backup herstellen.
- den tatsächlich verfügbaren Recovery-Weg und seine Voraussetzungen vorab
  belegen.

`restore_path_verified` beziehungsweise ein gleichbedeutender
Recovery-Nachweis bedeutet:

- das vor der riskanten Mutation erzeugte Backup ist mechanisch lesbar;
- der tatsächlich verfügbare Recovery-Weg und seine Voraussetzungen sind
  vorab verifiziert;
- ein destruktiver Restore gegen Produktionsdaten muss nicht ausschließlich
  zu Testzwecken ausgeführt werden;
- wenn ein zerstörungsfreier isolierter Restore-Roundtrip verfügbar ist,
  wird er verwendet;
- wenn ein solcher Roundtrip nicht verfügbar ist, sind für die Live-Abnahme
  stattdessen ein enger Mutationsscope, eine Baseline-/Nachkontrolle und ein
  Änderungs-Freeze während des Abnahmefensters Pflicht.

Ein bloßer Hinweis auf die Existenz irgendeiner Backup- oder
Cloud-Recovery-Funktion genügt nicht.

Reale Live-Mutationen im Entwicklungs-/Abnahmekontext benötigen jeweils
Eigentümerfreigabe.

Riskante Fähigkeiten werden erst nach ihrer passenden Abnahme aktiviert.

## §4 Eigentümerhandlungen

Claude Code führt ohne ausdrückliche Eigentümerhandlung insbesondere nicht
aus:

- Push,
- Force-Push,
- destructive cleanup ungesicherter Arbeit,
- sudo beziehungsweise protected install,
- globale Systemkonfiguration,
- Benutzeranlage,
- TCC-Freigabe,
- reale ausdrücklich freigabepflichtige Live-Mutation.

Claude Code darf sichere lokale Entwicklungsoperationen selbst ausführen.

## §5 Guard

Der Guard schützt vor echtem Schaden und unbeabsichtigten Side Effects.

Er soll insbesondere destructive Git-, Datei-, System- und
Produktionsaktionen blockieren oder owner-gaten.

Der Guard ist keine allgemeine Architektur-, Methodik- oder
Governance-Polizei.

Methodische Fragen werden nicht durch zusätzliche Guard-Sperren gelöst, wenn
kein reales Schadensrisiko besteht.

## §6 Ableiten statt behaupten

Eine Aussage gilt nur in dem Umfang, in dem sie aus tatsächlich beobachteter
Evidenz ableitbar ist.

Ein Pin, Digest, Commit, Gate oder Record beweist keine Strecke allein durch
seine Existenz.

Mindestens das für die Aussage relevante Ende beziehungsweise Ergebnis muss
beobachtet oder anderweitig mechanisch gebunden sein.

`unknown` und `unproven` sind niemals `pass`.

## §7 OID- und Integritätsregel

Commit-OIDs werden niemals geraten, vervollständigt oder aus ähnlichen
Identifiers abgeleitet.

Wenn ein Wert als Commit verwendet wird:

- vollständigen Wert mechanisch bestimmen,
- Existenz prüfen,
- Objekttyp Commit prüfen.

Integritäts- und Expectation-Werte müssen aus genau dem Subjekt ableitbar
sein, das sie schützen.

Andernfalls wird das Feld entfernt oder als rein beschreibend behandelt.

## §8 Kein falsches Grün

Eine verpflichtende Bedingung muss im tatsächlich ausgeführten Pfad
maschinenwirksam sein.

Fehlt eine Pflichtbedingung: kein PASS.

Ein Bericht, Warntext oder Kommentar darf eine nicht erzwungene Bedingung
nicht ersetzen.

Ein Gate-Ergebnis wird nicht nachträglich semantisch passend gemacht.

Wenn die Ursache des Ergebnisses falsch ist, gilt der Nachweis nicht.

## §9 Empty-/No-op-Schutz

Ein leerer oder ausgefallener Aggregations- oder Lesepfad darf keinen Erfolg
erzeugen, außer Leere ist selbst unabhängig die erwartete Aussage.

Mutationstests müssen zuerst beweisen, dass ihre Manipulation tatsächlich
stattgefunden hat.

Ein No-op darf keinen Mutationstest bestehen.

## §10 Konfiguration und Migration

Eine deklarierte aktive Konfiguration muss von genau dem realen produktiven
Loader gelesen werden, für den sie gedacht ist.

Keine Scheinkonfiguration.

Bei aktiv geladenen inkompatiblen Konfigurations- oder Datenmigrationen:
extend → migrate → narrow.

Diese Regel gilt nicht als Zeremonie für neue, noch nicht aktive isolierte
Datenstrukturen.

## §11 Single Source of Truth

Jede normative Regel hat genau eine normative Quelle.

Andere Dokumente dürfen:

- darauf verweisen,
- konkrete Prüfwerte oder Ergebnisse enthalten,

aber dieselbe Regel nicht unabhängig neu definieren.

Cross-Projekt-Eigentümerentscheidungen bleiben im bestehenden kanonischen
Decision Register.

Für neue Entscheidungen:

- freie ID einmal mechanisch auf Kollision prüfen,
- Entscheidung eintragen,
- fertig.

Kein Reservation-Ref-Verfahren und keine separate Reservierungszeremonie.

Die allgemeinen Dauerregeln selbst stehen ausschließlich in:

`docs/governance/openjarvis-dauerregeln.md`

in der kanonischen Tooling-/Kalender-Linie.

Andere Repository-Linien dürfen diese Regeln commitgebunden lesen, aber nicht
als zweite normative Kopie führen.

## §12 Testregel

Normale Produktänderung:

- gezielte Tests des geänderten Pfads,
- Build/Typecheck soweit relevant,
- ein End-to-End-Durchlauf mit Fixture/disposable Daten.

Safety-, Gate- oder Guard-Regeländerung zusätzlich:

- Test, der ohne Reparatur den Fehler reproduziert,
- Gegen- beziehungsweise Negativtest, der beweist, dass die ursprüngliche
  Verletzung weiterhin erkannt wird.

Keine Volltestpflicht bei jeder kleinen Änderung.

Nach Scope-Änderung werden nur die tatsächlich betroffenen Prüfungen erneut
gefahren.

## §13 Live-Abnahme

Live-Abnahme ist nur notwendig, wenn die zu beweisende Funktion von einem
realen externen System, nativer Plattformfunktion oder realem Side Effect
abhängt.

Dann wird genau der betroffene reale Pfad geprüft.

Kein Live-Gate nur aus Zeremonie.

Bei UI reicht zusätzlich eine Eigentümer-Sichtprüfung, wenn keine
automatisierbare Wahrheit fehlt.

## §14 Plattformen

x86_64 und arm64 bleiben unterstützte native Releaseziele, solange der
Eigentümer dies nicht ändert.

Native Plattformabnahme wird jedoch nur erneut verlangt, wenn:

- der relevante plattformspezifische Pfad geändert wurde,
- eine frühere Abnahme nicht mehr auf den aktuellen Pfad übertragbar ist,
- oder ein Release-Smoke für das unterstützte Ziel ansteht.

Ein unveränderter bereits akzeptierter nativer Pfad muss nicht nach jedem
anderen Block erneut getestet werden.

Release-Smokes dürfen gebündelt werden.

Rosetta ersetzt keinen erforderlichen nativen Plattformnachweis.

## §15 Minimaler Blockabschluss

Ein normaler Block ist fertig, wenn:

1. seine konkrete Erfolgsbedingung erfüllt ist,
2. relevante gezielte Tests beziehungsweise Buildchecks grün sind,
3. der zentrale Pfad einmal End-to-End nachgewiesen wurde,
4. bei UI die nötige Eigentümer-Sichtprüfung erfolgt ist,
5. ein kurzer Abschlussrecord den getesteten Commit oder Zustand, das
   Ergebnis und bekannte Grenzen bindet.

Kein obligatorischer eigener `module-final`-Schritt.

Kein obligatorischer separater Evidenzcommit.

Kein obligatorischer Fünf-Phasen-Lauf.

Riskante Blöcke ergänzen nur die für ihr konkretes Risiko notwendigen
Safety- und Live-Nachweise.

## §16 Bericht und Evidenz

Bericht ist Folge des getesteten Zustands, keine zweite Wahrheit.

Evidence wird nur in dem Umfang gespeichert, der die Aussage tatsächlich
trägt.

Kompakter maschinenlesbarer Abschlussnachweis ist Standard.

Raw Logs werden dauerhaft aufgehoben, wenn sie benötigt werden für:

- reale oder destruktive Live-Mutationen,
- einen strittigen oder fehlgeschlagenen Nachweis,
- eine Aussage, die ohne Raw Evidence nicht reproduzierbar wäre.

Keine Evidenzproduktion um ihrer selbst willen.

## §17 Commits

Keine Commitbudgets.

Keine `max_commits`.

Keine Positionsnummern.

Keine authorized-overrun-Buchhaltung.

Commits werden nach fachlich kohärenten Änderungen geschnitten.

Normative Änderung und Evidence dürfen im selben Commit liegen, wenn die
Aussage dadurch nicht zirkulär wird.

Wenn ein Nachweis zwingend eine bereits fixierte Commitidentität benötigt,
folgt dafür ein separater evidenzieller Commit.

Keine feste Commitzahl.

## §18 Scope-Änderungen

Ein Block darf seinen Scope erweitern, wenn ein mechanisch festgestellter
Blocker unmittelbar gelöst werden muss, damit seine Funktion erreicht werden
kann.

Kurze Delta-Begründung genügt.

Kein neuer Meta- oder Qualitätsblock, wenn die Reparatur Teil des aktuellen
Funktionswegs ist.

## §19 Module sind unabhängig

Ein Modul blockiert den fachlichen Abschluss eines anderen nur bei einer
echten technischen Abhängigkeit.

Historische Reihenfolgen oder Governance-Kopplungen reichen nicht.

Calendar und Contacts führen ihre eigenen tatsächlichen Status.

Eine spätere Produktfreigabe kann separat verlangen, dass alle für diesen
Release beworbenen Fähigkeiten akzeptiert sind.

Die bisherige generelle Kopplung „Calendar-Abschluss wartet auf Contacts-M2"
entfällt.

## §20 Funktionsvorrang / F1 V2

Funktionsvorrang bleibt.

Es werden keine eigenständigen Qualitäts-, Governance- oder
Methodikprojekte gestartet, solange nutzbare Produktfunktion fehlt.

F1 verbietet aber nicht mehr jede parallele Arbeit.

Erlaubt sind gleichzeitig:

- eine Risk Lane,
- eine davon unabhängige Safe Product Lane.

Qualitäts- oder Governance-Reparaturen sind erlaubt, wenn sie einen konkreten
aktiven Funktionspfad mechanisch blockieren oder realen Schaden verhindern.

Eine einmalige Eigentümerangeordnete Migration bestehender Regeln auf diese
Single Source gilt als Inkraftsetzung, nicht als neue dauerhafte
Governance-Lane.

## §21 Produktpriorität

Connector-Perfektion ist kein Selbstzweck.

Nach dem engen Abschluss der bereits begonnenen Contacts-/Calendar-Arbeit hat
der tatsächlich nutzbare Jarvis-Kern Vorrang.

Priorität:

1. Jarvis Core / Shell / Command Routing / Active Context
2. Memory + Spaces
3. Security Boundary / Injection-Schutz / Credential-Haltung / Backup
4. Planner + Operator
5. bestehende Calendar-/Contacts-Fähigkeiten in den Operator integrieren
6. Trading Intelligence T1
7. danach neue Spezialmodule nach Eigentümerentscheidung

Die Safe Product Lane darf mit Punkt 1 beginnen, während die Risk Lane noch
Contacts-M2 abschließt.

## §22 Gestrichene alte Prozessregeln

Nicht mehr verbindlich sind:

- max_commits,
- Commitpositionen,
- authorized_overrun,
- decided_by-Buchhaltung für Commitpläne,
- R2-Reservierungszeremonie,
- obligatorischer module-final-Schritt,
- obligatorische fünf Gatephasen je Block,
- obligatorische getrennte Normativ-/Evidence-Commits,
- blanket nur ein aktiver Block,
- blanket Vollabnahme auf beiden Macs nach jedem Block,
- FAIL-vs-BLOCKED-Debatten ohne Verhaltenswirkung,
- parallele normative Wiedergabe derselben Regel in mehreren Dokumenten,
- starres Verbot jeder Scope-Erweiterung.

Bestehende historische Artefakte bleiben historische Evidenz.

Sie müssen nicht rückwirkend umgebaut werden.

## §23 Leitprinzip

So wenig Prozess wie möglich.

So viel Sicherung wie für den realen Schaden und die Wahrheit notwendig.

Geschwindigkeit wird nicht durch Weglassen von Sicherheitsbeweisen erreicht,
sondern durch Weglassen von Zeremonie, Wiederholungen und Prüfungen ohne
zusätzliche Aussagekraft.

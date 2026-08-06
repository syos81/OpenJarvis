---
Status: normativ (B0a-2 Governance); allgemeine, konfigurationsgetriebene Modullandkarte
Maschinelle Quellen: config/governance/delivery-order.json, config/governance/generality-scope.json
---

# B0a-2 — Allgemeine Modullandkarte

## §1 Allgemeinheitsregel

Grundlage sind:

* DEC-002 (jarvis/rebuild-v1@c222601, „Providerneutrale Capability-Verträge je Fachbereich; keine Mega-Schnittstelle; MCP nur möglicher Adapter")
* DEC-011 (jarvis/rebuild-v1@c222601, „Workspaces/Rollen/Tags/Organisationen/Beziehungen als konfigurierbares Modell; nie hart codiert")
* DEC-039 (jarvis/rebuild-v1@c222601, „Initiale Workspaces: Privat, Arbeit, Hausverwaltung — konfigurierbare Werte, keine hartcodierte Fachlogik; umbenennbar, ergänzbar, später archivierbar (löst DEC-D15)")
* DEC-018 (jarvis/rebuild-v1@c222601, „Vertikale Modulentwicklung, Materialisierungsregel, Definition of Done")
* DEC-047 (jarvis/rebuild-v1@c222601, „KI-Arbeit, Internet, Browser- und App-Steuerung als verbindliches Zielbild")

**Verbindliche Regel:**

> Allgemeinheit gilt ab dem ersten realisierten Fall als Vertrags- und
> Konfigurationsregel. Eine gemeinsame Engine wird jedoch erst beim zweiten realen,
> fachlich unterschiedlichen Fall aus mindestens zwei belegten Implementierungen
> extrahiert.

Daraus folgt:

* Kein Schema, Enum, Zustand, Feld, Routensegment, Typname oder Modulname enthält
  eine konkrete Organisation.
* Organisationen, Workspaces, Rollen, Fachbereiche, Tags und Vorgangstypen sind
  Konfigurations- oder Datenwerte.
* Provider- und Produktnamen sind nur in ausdrücklich freigegebenen Adapter-,
  Manifest- und Capability-Pfaden zulässig.
* Fachbegriffe eines echten kanonischen Bestands bleiben zulässig; Allgemeinheit
  bedeutet **nicht** Fachbegriffslosigkeit.
* Der erste Vorgangsfall wird konfigurierbar und organisationsneutral gebaut, aber
  nicht vorsorglich als universelle Plattform.
* Erst beim zweiten realen Vorgangsfall wird ausschließlich die nachgewiesene
  gemeinsame Schnittmenge extrahiert.

## §2 Korrigierte Einordnung

### §2.1 CRM und Akquise — kein eigenes Fachmodul

Kontakte bleiben kanonischer Bestand. Lead, Opportunity, Pipeline, Nachfassen,
Angebot und Abschluss sind **konfigurierbare Vorgänge und Beziehungen** auf Kontakten
und Organisationen. Es entsteht kein CRM-Fachmodul und keine CRM-spezifische
Kernlogik.

### §2.2 Office und DART — als Modul entfernt

Ein Modul „Office" oder „DART" existiert nicht.

* „Arbeit" beziehungsweise „Office" ist ein Workspace oder Fachbereich.
* Der Organisationswert ist ein Datenwert, kein Modul- oder Typname.
* Ein A1-Antrag ist ein **Vorgangstyp** mit Formular, Frist, Nachweis und Ablage.

### §2.3 Verträge und Fristen — eigener kanonischer Bestand

Verträge bleiben ein eigener kanonischer Bestand mit Parteien, Fassungen,
Gültigkeit, Pflichten, Verlängerung und Beendigung. Prüf-, Verlängerungs- und
Kündigungsvorgänge dürfen Verträge referenzieren, ersetzen deren kanonischen Bestand
aber nicht.

### §2.4 Weitere Vorgangskonfigurationen

Hausverwaltungs-Vorgänge, Hausverwaltungs-Vermietung, CRM/Akquise, Office-Vorgänge
und Reisen sind zunächst **Konfigurationen derselben allgemeinen Vorgangsfähigkeit**,
soweit keine gesonderte Datenhoheitsentscheidung etwas anderes belegt.

Reisen bleibt eine Vorgangskonfiguration, solange Jarvis Buchungen, Reisepläne,
Belege oder Abrechnungen nicht ausdrücklich selbst kanonisch führen soll.

### §2.5 Hausverwaltung — Funktionsbereiche, keine Volldatenbank

Hausverwaltungsbereiche sind Funktionsbereiche und **keine** automatisch
freigegebenen getrennten Fachmodule oder Volldatenbanken. Maßgeblich sind:

* DEC-048 (jarvis/rebuild-v1@c222601, „Hausverwaltungs-Systemgrenzen und Workspace-Sicherheitskontexte")
* ADR-0023 (jarvis/rebuild-v1@c222601, „Hausverwaltungs-Systemgrenzen, Immoware24 und Workspace-Sicherheitskontexte")

Ohne neue ausdrückliche Datenhoheitsentscheidung darf Jarvis nicht aufbauen:

* eine konkurrierende Volldatenbank der Hausverwaltung,
* ein paralleles Buchungswerk,
* eine vollständige zweite Bankdatenhaltung,
* eine konkurrierende Abrechnungsdatenbank.

Vor einer Implementierung sind feld- und operationsgenau festzulegen: führendes
System, erlaubte Projektionen, Jarvis-eigene Arbeitszustände, Integrationsweg,
Verifikation, Audit und Kompensation.

## §3 Mechanische Prüfungen

Die Allgemeinheitsregel wird nicht nur behauptet, sondern in der B0a-1-Gate-Engine
mechanisch geprüft. Es gibt genau drei Prüfungen; sie sind in
`config/governance/generality-scope.json` deklariert.

### §3.1 Organisations-Namensscan

Eine zentrale, versionierte Liste konkreter Organisationsnamen und ihrer
Schreibvarianten wird tokengenau und unicode-normalisiert gegen Schemata,
Migrationen, Tabellen-, Spalten- und Indexnamen, Enums, Zustandsbezeichner, Typen,
Klassen, Interfaces, Funktionen, Modul-, Datei- und Verzeichnisnamen, Routen und
API-Pfade, Kernlogik sowie fest codierte Standardwerte geprüft.

Der Scan ist **kein** naiver globaler Substringtest: er normalisiert Schreibweisen,
achtet auf Identifier- und Tokengrenzen und wendet präzise Pfadregeln an. Zulässige
Bereiche sind ausschließlich ausdrücklich gekennzeichnete Konfigurationsdaten,
bewusst gekennzeichnete Testfixtures und historische oder erklärende Dokumentation.
Jede Ausnahme braucht exakten Pfad, Begründung, Regelinhaber und Test.

Der Check ist baselinefähig gegen den Commit `7986bee`: ein bereits dort vorhandener,
strukturell identischer Befund wird als `pass_with_baseline` ausgewiesen, ein neuer
oder zusätzlicher Befund ist `fail`.

### §3.2 Providerpfad-Gate

Providerbegriffe dürfen nur in ausdrücklich freigegebenen Bereichen vorkommen:
Adapter, Providermanifeste, Capability-Implementierungen und die zugehörigen
providerbezogenen Tests. Das Gate schlägt fehl bei Providernamen in Kernschema,
allgemeiner Zustandslogik, allgemeinen Modul- oder Typnamen, providerneutralen
Routen, generischen Vorgangsverträgen und fest codierten Kernentscheidungen. Es gibt
keine pauschale globale Allowlist; jede Freigabe ist pfadgenau.

### §3.3 Positiver Konfigurationstest

Der entscheidende Beweis ist ein positiver Test mit zwei vollständig erfundenen
Organisationen, zwei unterschiedlich konfigurierten Vorgangstypen, unterschiedlichen
Zuständen, Rollen, Fristen und fälligen Aktionen — bei identischem, unverändertem
Kerncode. Er beweist, dass beide Konfigurationen ohne Codeänderung, ohne neuen
Enumwert, ohne zusätzliche Route, ohne organisationsspezifische Verzweigung und ohne
providerbezogene Kernlogik geladen und verarbeitet werden.

Zusätzlich verbietet ein AST-basierter Check im Kern fest codierte Literalvergleiche
auf Organisations-IDs oder -Namen, Workspace-IDs, Vorgangstyp-IDs,
fachbereichsspezifische Zustandsnamen und Providerwerte außerhalb der Adaptergrenze.
Ein Namensscan allein gilt nicht als Konfigurierbarkeitsnachweis.

**Aktivierungsregel ohne Produktcode:** Solange nachweislich kein Vorgangsschema,
keine Vorgangsroute und keine Vorgangskernlogik existieren, ist der positive
Produkttest `not_applicable`; der Gate-eigene Mechanismustest muss trotzdem `pass`
sein. Sobald ein einschlägiger Produktpfad entsteht, wird der positive
Konfigurationstest automatisch verpflichtend. Ein vorhandener einschlägiger
Produktpfad bei weiterhin `not_applicable` ist `fail`. Eine spekulative
Vorgangs-Engine wird nicht gebaut.

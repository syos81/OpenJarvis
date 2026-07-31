---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-2, AV-3, AV-33, AV-36
Zugehörige ADRs: ADR-0012 (ergänzt/ersetzt dessen Punkt 4), ADR-0018, ADR-0024
Verwandte DEC-Einträge: DEC-018, DEC-030, DEC-042, DEC-043, DEC-045, DEC-050; löst DEC-D10 vollständig
---

# ADR-0019: Verbindliche Modulreihenfolge und 100-Prozent-Modulvollendung

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Der formal abgenommene OpenJarvis Connector-, Capability- und Reuse-Audit (2026-07-31; Kanon: Abschlussbericht, zweite Fassung des Ergänzungs-, Korrektur- und Abnahmeberichts, kanonischer Abnahme-Nachtrag, letztes Korrekturblatt; übernommen per DEC-044/ADR-0020) hat belegt, dass der Upstream-Bestand aus breit angelegten, teilfertigen Flächen besteht (registrierte, aber nie erreichbare Tools; Scheduler mit Dry-run-Defekt; Connectoren ohne Löschsemantik). Der Eigentümer hat daraufhin die Modulreihenfolge bis Modul 3 festgelegt und die vertikale Regel aus ADR-0012 verschärft. ADR-0012 Punkt 4 („Reihenfolge offen, DEC-D10") wird durch diesen ADR ersetzt; die Punkte 1–3 von ADR-0012 gelten unverändert fort.

## Entscheidung

1. **Verbindliche Reihenfolge (DEC-045):** Modul 1 **Kontakte** (DEC-030) → Modul 2 **Kalender** → Modul 3 **Trading Intelligence (T1, ADR-0024)**. Zwischen diesen Modulen darf kein anderes Fachmodul eingeschoben oder parallel begonnen werden; jede Abweichung erfordert eine neue ausdrückliche Architekturentscheidung (DEC-Eintrag). **Nach Modul 3 wird die weitere Reihenfolge bewusst neu entschieden.** Hausverwaltung, Life OS, Mail und weitere Trading-Stufen bleiben verbindliche Zielbereiche, erhalten aber jetzt keine festgelegte Position nach Modul 3.
2. **Ein-Modul-Regel:** Es wird immer nur genau **ein** Fachmodul aktiv umgesetzt. Ein neues Fachmodul darf erst begonnen werden, wenn das vorherige zu 100 Prozent abgeschlossen, produktiv abgenommen, dokumentiert und sauber integriert ist (Definition of Done 19 einschließlich 19 §11).
3. **Unzulässig sind insbesondere:** horizontaler Aufbau vieler halbfertiger Module · vorsorgliche Implementierung später benötigter Fachfunktionen · parallele Spikes für spätere Fachmodule · provisorische UI ohne fertiges Backend · Backend ohne vollständige UI · read-only-Teilmodule ohne beschlossene vollständige Mutationsstrecke · spätere Verschiebung notwendiger Sicherheits-, Restore- oder Plattformarbeiten · „vorerst ausreichend", wenn dadurch ein Modul nicht produktionsreif ist · Fertigmeldungen mit offenen Release-, Plattform- oder Modulgates.
4. **Materialisierungsregel (AV-33, bekräftigt):** Gemeinsame Grundlagen werden nur implementiert, wenn das aktuell aktive Fachmodul sie konkret benötigt, und müssen innerhalb dieses Moduls vollständig produktionsreif werden. Es darf kein vorsorglicher, halbfertiger Operator-, Browser-, Mail-, Automations-, Trading- oder Hausverwaltungs-Unterbau entstehen.
5. **Vollständige Modulabnahme:** Der verbindliche Mindestkatalog steht in 19 (§1–§10) und wird durch **19 §11** um die vom Eigentümer geforderten Punkte ergänzt (u. a. Suche und kontrollierte Projektion, Export, getestete Wiederherstellung, Retention und Löschweitergabe, Provenienz, Produktions-Build/Packaging/Signierung, produktiver Livelauf auf **arm64 und x86_64**, abschließender Qualitätsaudit, sauberer Commit und kontrollierte Integration). Beide macOS-Zielarchitekturen sind gleichwertig; Intel x86_64 ist **kein** Kompatibilitätstest (ADR-0018).
6. **Kontakte-Status:** Kontakte ist das einzige aktive Fachmodul und **nicht abgeschlossen**. Für Fertigmeldung und produktive Auslieferung mit Kontakte-Modul gelten die acht Gates aus DEC-050 (kanonisch: `docs/personal-jarvis/modules/contacts.md` §19).

## Geprüfte Alternativen

- **Reihenfolge weiterhin offen lassen** — verworfen: Der Eigentümer hat entschieden; eine offene Reihenfolge hat im Upstream nachweislich horizontale Flächen begünstigt.
- **Vollständige Reihenfolge aller 15 Module jetzt festlegen** — verworfen: erfundene Prioritäten ohne Entscheidungsgrundlage; nach Modul 3 wird bewusst neu entschieden.
- **Parallele Vorbereitung von Modul 2/3 (Spikes) während Modul 1** — verworfen: verstößt gegen die Ein-Modul-Regel; der EventKit-Spike beginnt erst innerhalb des Kalender-Moduls.

## Konsequenzen

Die Modulkarte (16) trägt die Reihenfolge bis Modul 3; 19 erhält §11; DEC-D10 ist vollständig aufgelöst. Kein Kalender-, Trading-, HV-, Operator-, Browser- oder Automationscode entsteht vor dem jeweils zuständigen Modul.

## Verweise

Primärdokumente: 16 (§4.2), 19 (§11), modules/contacts.md (§19). Entscheidungen: DEC-045, DEC-050. Ersetzt: ADR-0012 Punkt 4.

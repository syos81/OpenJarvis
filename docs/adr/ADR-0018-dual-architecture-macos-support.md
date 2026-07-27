---
Status: normativ
Architektur-Baseline: v3 (Änderung von AV-29)
Freigabedatum: 2026-07-27
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-2, AV-26, AV-28, AV-29
Zugehörige ADRs: ADR-0012, ADR-0016 (ergänzt); ADR-0014, ADR-0015 (Packaging-Berührung)
Verwandte DEC-Einträge: DEC-042 (neu); ergänzt DEC-009, DEC-034, DEC-038
---

# ADR-0018: Gleichwertige Dual-Architektur-Unterstützung für macOS (arm64 und x86_64)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

AV-29 und DEC-009 bezeichnen bisher „macOS Apple Silicon primär, Linux sekundär" als Plattformaussage. Diese Formulierung lässt Intel x86_64 als optionale Kompatibilitätsplattform erscheinen und deckt die Betriebsrealität des Eigentümers nicht ab: Personal Jarvis muss auf **beiden** macOS-Architekturen produktiv laufen.

Auslöser ist der Kontakte-Bridge-Spike (ADR-0016, DEC-031), der auf zwei Geräten unterschiedlicher Architektur fortgeführt wurde:

- **Apple Silicon arm64** (Quellgerät, Swift 6.3.2, SDK 26.5): Phase A vollständig — Sidecar-Build, P0-Shim-Reachability, JSON-Lines-Protokoll 18/18, T3-Ad-hoc-Packaging und T4-signiertes Packaging bestanden.
- **Intel x86_64** (Zielgerät, Swift 5.7.2, SDK 13.1, macOS 12.7.6): kontaktfreie Phase-A-Reproduktion — Sidecar-Build, P0-Shim-Reachability und JSON-Lines-Protokoll 18/18 bestanden; T3/T4-Packaging dort noch offen.

Die Reproduktion legte zugleich drei arm64-Festverdrahtungen in den Spike-Werkzeugen offen (Default-`TARGET` in beiden Build-Skripten, architekturblinde Sidecar-Auflösung im Host-Treiber). Sie waren in der Werkzeugschicht lokalisiert; die Swift-/Objective-C-Quellen, das JSON-Lines-Protokoll und die DTOs enthielten **keine** Architekturannahme.

Die Prüfung der Contacts-API-Verfügbarkeit ergab als effektive Untergrenze **macOS 12.3** (`CNSaveRequest.transactionAuthor` ab macOS 12, `CNSaveRequest.shouldRefetchContacts` ab macOS 12.3; Change-History-API bereits ab macOS 10.15). Beide Eigenschaften sind in SDK 13.1 vorhanden, die Untergrenze ist damit auf beiden Architekturen belegt und keine bloße Annahme.

Der Eigentümer hat am 2026-07-27 entschieden, beide Architekturen als gleichwertige Produktionsziele zu führen. Diese Änderung berührt einen geschützten Bereich (01 §3) und erfordert daher diesen ADR (AV-30).

## Entscheidung

**Personal Jarvis unterstützt macOS auf Apple Silicon arm64 und Intel x86_64 als gleichwertige produktive Zielplattformen. Beide Architekturen erhalten denselben fachlichen Funktionsumfang. Für Apple Silicon arm64 und Intel x86_64 muss jeweils nativer ausführbarer Code gebaut und nachgewiesen werden. Laufzeit-, Sicherheits-, TCC- und Live-Abnahmen erfolgen separat auf echter Hardware der jeweiligen Architektur. Signierung, Packaging und Update-Auslieferung müssen sicherstellen, dass für beide Architekturen der korrekte native Code bereitgestellt und überprüft wird. Ob dies durch ein gemeinsames Universal-2-Artefakt oder durch zwei getrennte architekturspezifische Pakete erfolgt, bleibt bis zur Entscheidung DEC-D17 offen. Ein Modul gilt auf macOS erst als vollständig fertig, wenn die verpflichtenden Abnahmen auf beiden Architekturen bestanden sind.**

Im Einzelnen:

1. **Gleichwertigkeit.** Keine Fachfunktion, keine Sicherheitsregel, keine UI-Fläche und keine Capability-Operation darf auf eine Architektur beschränkt sein. Intel x86_64 ist kein freiwilliger Zusatztest und keine zweitrangige Plattform.

2. **Mindestversion.** Die verbindliche Mindestversion ist **macOS 12.3** auf **beiden** Architekturen. Sie folgt aus der Contacts-API-Untergrenze (`transactionAuthor`, `shouldRefetchContacts`) und gilt einheitlich für App, Native Bridge und Sidecar. Eine niedrigere Angabe in der Packaging-Konfiguration ist ein Defekt und vor produktivem Desktop-Betrieb zu korrigieren.

3. **Architekturneutrale Fachschicht.** Fachmodule, Verträge, DTOs und Protokolle enthalten **keine** architekturabhängige Logik (AV-4). Architekturabhängigkeit ist ausschließlich in der Werkzeugschicht zulässig — Build-Skripte, Packaging, CI — und dort mit Host-Erkennung plus ausdrücklichem Override statt festverdrahteter Architektur.

4. **Getrennte Pflichtabnahme auf echter Hardware.** Geräteabhängige Nachweise sind je Architektur auf physischer Hardware der jeweiligen Architektur zu erbringen: TCC-Verhalten und -Persistenz, Codesigning mit gerätelokalem Zertifikat, Bereitstellung und Prüfung des nativen Codes im ausgelieferten Artefakt, CRUD, Feldabdeckung, Change History, Fallback-Voll-Diff, Unified Contacts, Betrieb aus der gepackten App, App-Neustart, Backup/Restore und Live-Abnahme. **Ein Ergebnis der einen Architektur gilt niemals automatisch für die andere.** Diese Abnahmepflicht ist **formatunabhängig**: Sie gilt unverändert, ob der native Code aus einem gemeinsamen Universal-2-Artefakt oder aus einem architekturspezifischen Paket stammt.

5. **Rosetta ist kein Ersatz für die native Abnahme.** Rosetta 2 übersetzt ausschließlich in **eine** Richtung: x86_64-Binaries laufen übersetzt auf Apple Silicon. Es gibt **keinen** umgekehrten Weg — eine arm64-Anwendung ist auf einem Intel-Mac grundsätzlich nicht ausführbar, weder nativ noch emuliert. Daraus folgt:
   - Ein x86_64-Build, der auf Apple Silicon unter Rosetta ausgeführt wird, ersetzt **nicht** die Prüfung auf echter Intel-Hardware: es laufen ein übersetzter Codepfad und eine andere Betriebssystem-/Prozessorumgebung, und die Prozessattribution gegenüber TCC und Codesigning ist nicht identisch mit dem nativen Fall.
   - Die arm64-Abnahme ist auf Intel-Hardware **technisch unmöglich** und daher zwingend auf Apple-Silicon-Hardware zu erbringen.
   - Rosetta darf in keiner Abnahmezeile als bestandener Nachweis geführt werden.

6. **Toolchain.** Python **exakt 3.12** bleibt für produktive Builds, Tests und den Kontakte-MASTER verpflichtend; ebenso uv, Rust stable ≥ 1.88, maturin und Node.js 22+ (AV-29). Eine ältere Python-Version, die für isolierte kontaktfreie Spike-Skripte ausgereicht hat, ist **keine** produktive Toolchain-Abnahme und darf nicht als solche geführt werden.

7. **Auslieferungsformat weiterhin offen — DEC-D17.** Die Wahl zwischen einem **gemeinsamen signierten Universal-2-Artefakt** und **zwei getrennten signierten architekturspezifischen Release-Artefakten** wird durch diesen ADR **nicht** entschieden; sie ist als **DEC-D17** als offene Entscheidung registriert (17 §2). Keine Formulierung dieses ADR und keines Fachdokuments darf eines der beiden Formate vorschreiben oder ausschließen. Beide Varianten erfüllen die obige Entscheidung, solange für beide Architekturen der korrekte native Code bereitgestellt, überprüft und je Architektur auf echter Hardware abgenommen wird. Eine unverbindliche Empfehlung zugunsten von Universal 2 besteht (der Bestand baut bereits `--target universal-apple-darwin` und lädt beide Sidecar-Triples), ist aber ausdrücklich **nicht beschlossen** und in keinem Dokument als akzeptiert zu führen.

## Geprüfte Alternativen

- **Intel als „unterstützt, aber sekundär" beibehalten** — verworfen: widerspricht der Eigentümerentscheidung und erzeugt eine faktisch ungeprüfte Produktionsplattform. AV-29 verlangt ausdrücklich, dass nichts als unterstützt behauptet wird, das nicht geprüft ist.
- **Rosetta-Betrieb einer arm64-App auf Intel** — verworfen, weil technisch unmöglich (Rosetta übersetzt nur x86_64 → arm64).
- **x86_64-Build unter Rosetta auf Apple Silicon als Intel-Abnahme werten** — verworfen: übersetzter Codepfad, abweichende Prozessattribution gegenüber TCC und Codesigning, keine Aussage über native Intel-Hardware.
- **Ein Auslieferungsformat bereits hier festlegen** (Universal 2 oder zwei getrennte Pakete) — verworfen: die dafür nötigen Packaging-, Codesigning-, TCC-, Updater- und Rollback-Nachweise liegen noch nicht vor. Die Frage wird als **DEC-D17** offen geführt; dieser ADR schreibt daher kein Format vor.
- **Ein Auslieferungsformat ohne getrennte Abnahme genügen lassen** — verworfen: ein Artefakt belegt nur die Baubarkeit des nativen Codes, nicht dessen Laufzeitverhalten. TCC, Kontakte-Zugriff und Live-Abnahme bleiben je Architektur auf echter Hardware nachzuweisen — unabhängig vom gewählten Format.
- **Architekturabhängige Zweige in Fachmodulen** (z. B. reduzierter Funktionsumfang auf Intel) — verworfen: Verstoß gegen AV-4 und gegen die Gleichwertigkeitsentscheidung.
- **Mindestversion 10.15 beibehalten** — verworfen: die Contacts-Bridge benötigt `transactionAuthor` (macOS 12) und `shouldRefetchContacts` (macOS 12.3); eine niedrigere Angabe wäre eine unbelegte Behauptung (AV-3, AV-29).

## Auswirkungen auf Tests und Definition of Done

- **Tests (15):** Die nativen macOS-Tests (15 §1 Nr. 7) laufen auf Runnern **beider** Architekturen. Live-Abnahme (Nr. 11) und Desktop-Regression (Nr. 12) sind je Architektur zu erbringen. Der Restore-Drill (15 §1 Nr. 10, 13 §7) wird je Architektur durchgeführt. CI weist für jedes macOS-Release-Artefakt nach, dass der native Code beider Architekturen bereitgestellt wird — als Slices innerhalb eines Artefakts oder als je ein architekturspezifisches Artefakt; fehlender nativer Code für eine Architektur ist ein Build-Fehler, kein Hinweis.
- **Definition of Done (19):** Ein Modul ist auf macOS erst abgeschlossen, wenn die Abnahmematrix in **beiden** Spalten vollständig bestanden ist. Bereits als abgeschlossen geführte Module ohne Dual-Architektur-Abnahme gelten rückwirkend als nicht abgeschlossen.
- **Evidenzführung:** Spike-Nachweise sind technische Vor- bzw. Teilnachweise und keine Modulabnahme. Jede Abnahmezeile trägt Architektur, macOS-Version, Swift-/SDK-Version, Zertifikatsbezeichnung, Testbenutzer und Datum; ein Toolchain-Wechsel entwertet die betroffenen Zeilen.

## Konsequenzen

Die Abnahmefläche und der Hardwarebedarf verdoppeln sich; jede Modulfertigstellung benötigt Zugriff auf ein Apple-Silicon- **und** ein Intel-Gerät. Im Gegenzug wird die Plattformunterstützung belegt statt behauptet — genau das, was AV-3 und AV-29 („nichts anderes wird behauptet") verlangen. Die Werkzeugschicht wird geringfügig komplexer (Host-Erkennung, Nachweis des nativen Codes je Architektur), die Fachschicht bleibt unberührt und damit weiterhin Linux-portabel. Linux bleibt sekundäres späteres Ziel ohne Abnahmepflicht in dieser Baseline.

Offen bleibt einzig das Auslieferungsformat (Punkt 7, **DEC-D17**). Solange es offen ist, gilt für den Spike- und Entwicklungsbetrieb der Build je Architektur; das ist eine Arbeitsweise während der Entwicklung und **keine** Vorentscheidung über das Release-Format. Die Festlegung erfolgt spätestens vor dem ersten produktiven Desktop-Release und vor endgültiger Festlegung von Updater-Manifest und Release-Artefakten.

## Verweise

Primärdokumente: 15 §6 (AV-29), 15 §1 (AV-26/AV-28), 19 (AV-2), 08 §4 (Native Bridge), 13 §7 (Restore-Drill), 17 §2 (DEC-D17). Regeln: AV-2, AV-26, AV-28, AV-29 (zusätzlich berührt: AV-3, AV-4). ADRs: ADR-0012 (vertikale Modulentwicklung und DoD), ADR-0016 (Swift-Contacts-Bridge). Entscheidungen: **DEC-042** (accepted); **DEC-D17** (offen, Auslieferungsformat); ergänzt DEC-009, DEC-034, DEC-038.

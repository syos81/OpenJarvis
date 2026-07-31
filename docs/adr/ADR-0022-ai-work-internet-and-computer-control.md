---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-8, AV-16, AV-33, AV-35
Zugehörige ADRs: ADR-0009 (Egress default-deny), ADR-0019, ADR-0021
Verwandte DEC-Einträge: DEC-016, DEC-047
---

# ADR-0022: KI-Arbeitsaufträge, Internet-, Browser- und App-Steuerung (verbindliches Zielbild)

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Personal Jarvis soll langfristig nicht nur antworten, sondern **arbeiten**: dauerhafte Aufträge ausführen, im Internet recherchieren, Browser und macOS-Anwendungen kontrolliert bedienen. Diese Fähigkeiten werden hiermit als verbindliches Produktziel festgeschrieben — **ohne** jetzige Implementierung und ohne vorsorglichen Unterbau (ADR-0019).

## Entscheidung

1. **KI-Arbeitsmodus (Zielbild, verbindlich):** dauerhafte Arbeitsaufträge statt ausschließlich flüchtiger Chats · selbstständige Arbeitsplanung · längere Hintergrundaufträge · Fortschritt, Pause, Fortsetzung und Abbruch · persistente Zwischenstände · Dateien und erzeugte Artefakte · gezielte Rückfragen bei echten Blockern · Quellen und Belege · Kosten- und Laufzeitgrenzen · Fortsetzung nach App-Neustart · nachvollziehbare Ergebnisübergabe. Arbeitsaufträge unterliegen dem Aktionsstufen- und Vertragsmodell aus ADR-0021.
2. **Internet und Recherche (Zielbild):** Websuche · Webseiten lesen und vergleichen · Quellen prüfen und speichern · aktuelle Informationen erkennen · News- und Themenbeobachtung · kontrollierte Downloads · Ausweis von Fakten, Unsicherheit und Aktualität. Jeder Cloud-/Netzabfluss von Personal-Daten bleibt fail-closed über den EgressGuard (12, ADR-0009).
3. **Browsersteuerung (Zielbild):** Webseiten öffnen und navigieren · Webanwendungen lesen · Formulare vorbereiten · Dateien hoch- und herunterladen · definierte Arbeitsschritte ausführen · **manuelle Übergabe bei Login, 2FA oder Captcha** · Erfolgsverifikation nach jeder Aktion. **macOS- und App-Steuerung (Zielbild):** Programme, Dateien und URLs öffnen · unterstützte öffentliche Schnittstellen verwenden · AppleScript, Shortcuts und Bedienungshilfen kontrolliert einsetzen · Browserautomation verwenden · **visuelle Bildschirm- und Maussteuerung nur als letzte Rückfallebene**.
4. **Architekturpriorität (verbindlich für jede künftige Integration):** (1) öffentliche API oder offizielle Integration → (2) dokumentierte Import-/Exportschnittstelle → (3) kontrollierte Browserautomation → (4) visuelle UI-Steuerung nur als Rückfall. Eine niedrigere Stufe ist nur zulässig, wenn die höheren nachweislich nicht verfügbar oder ungeeignet sind; die Prüfung wird dokumentiert.
5. **Prompt-Injection-Schutz (verbindlich):** Mail-, Web-, Dokument- und Providerinhalte sind **nicht vertrauenswürdige Daten**; Inhalte externer Quellen werden nie als Nutzer- oder Systemanweisung behandelt; Toolfreigaben werden unabhängig vom Sprachmodell deterministisch durchgesetzt (AV-8); versteckte Anweisungen dürfen keine Datenweitergabe oder Aktion auslösen; personenbezogene Daten werden nicht automatisch an Cloudmodelle weitergegeben (12); schreibende Aktionen benötigen eine deterministische Policy- und Capability-Prüfung (05, 10).
6. **Keine parallele Implementierung:** Diese Fähigkeiten werden erst in dem späteren Fachmodul produktionsreif gebaut, das sie **erstmals konkret benötigt** (z. B. Internetrecherche mit Quellen in Trading Intelligence T1, ADR-0024; Browserautomation frühestens mit einem HV-Modul, ADR-0023), und dort vollständig (ADR-0019). Die im Upstream vorhandenen Browser-/Exec-Tools bleiben bis dahin ungenutzt bzw. gemäß Register 20 gesperrt (u. a. SSRF-Prüfung vor jeder produktiven Nutzung, 02 §2.4).

## Geprüfte Alternativen

- **Generischer „Computer-Use"-Agent sofort** — verworfen: horizontaler Unterbau ohne Modulbedarf, ungeprüfte Sicherheitsfläche (ADR-0019, AV-33).
- **Visuelle UI-Steuerung als Primärweg** — verworfen: fragil, nicht verifizierbar; nur letzte Rückfallebene.

## Konsequenzen

Künftige Modulunterlagen prüfen Integrationen entlang der Prioritätenfolge und dokumentieren die Stufenwahl. Kein Code in diesem Auftrag.

## Verweise

Primärdokumente: 12, 05, 10. Entscheidungen: DEC-047. Zusammenhang: ADR-0021 (Aktionsstufen), ADR-0023 (HV), ADR-0024 (T1).

---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-21, AV-32
Zugehörige ADRs: ADR-0008
Verwandte DEC-Einträge: DEC-025, DEC-028
---

# ADR-0014: Einschränkung der Tauri-Kommando-Berechtigungen (DEV-2)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Architektur-Audit belegte, dass die Desktop-Webview upstream eine **breite `shell:allow-execute`-Berechtigung** besitzt und über das Tauri-Kommando `run_jarvis_command` **beliebige `jarvis`-Subkommandos** ausführen kann. Das lokale Vertrauensmodell des Personal-Betriebs (ADR-0008: die Webview ist die am wenigsten vertrauenswürdige Komponente; sie erhält nur kurzlebige, scope-begrenzte Tokens) wird dadurch ausgehebelt — ein Webview-Kompromiss ergäbe Shell-Zugriff. Diese Abweichung ist als **DEV-2** in der Abweichungsliste (18) geführt; dieser ADR ist ihr eigener Entscheidungsnachweis (DEC-028).

## Entscheidung

1. **Vor produktivem Personal-Betrieb der Desktop-App** wird die breite `shell:allow-execute`-Berechtigung der Webview eingeschränkt (Capability-Einengung auf den Sidecar-Scope in `frontend/src-tauri/capabilities/*`).
2. **`run_jarvis_command` ist für den Personal-Betrieb nicht allgemein aus der Webview erreichbar.**
3. Die Webview erhält **nur eng begrenzte, ausdrücklich benötigte Tauri-Kommandos** (z. B. API-Basis-Ermittlung, Bereitstellung des Desktop-Session-Tokens, Datei-Dialoge).
4. **Sidecar- und Prozessstart verbleiben im vertrauenswürdigen Tauri-Hauptprozess** (Supervisor-Rolle unverändert).
5. **Keine Fachmodul- oder React-Abhängigkeit von Tauri-internen Details:** Module und Komponenten bleiben transportneutral (AV-6, AV-9); optionale native Zusatzbestätigungen laufen nur über den transportneutralen ApprovalClient-Vertrag (DEC-D06, offen).
6. **Pflichten:** Capability-Regressionstest (die erlaubte Kommandofläche wird geprüft) und Desktop-Regressionstest (15 §1 Nr. 12) · Eintrag in der Abweichungsliste (18 DEV-2) · Re-Check bei jeder selektiven Upstream-Übernahme (AV-32).

## Geprüfte Alternativen

- **„Upstream-Berechtigungen unverändert lassen"** — **verworfen:** Die Webview könnte trotz Session-Token-Modell beliebige CLI-/Shell-Aktionen starten; das Sicherheitsmodell aus ADR-0008 wäre wirkungslos.
- **„Alle kritischen Funktionen über Tauri-Kommandos führen"** (Tauri-Proxy) — **verworfen:** Dadurch entstünde ein **zweiter produktiver Ausführungspfad** neben dem ApplicationCommandBus (Verstoß gegen AV-35) und eine Tauri-Kopplung von Fachmodulen und React-Komponenten (Verstoß gegen AV-6/AV-9); außerdem spaltete es den CLI-Pfad.

## Konsequenzen

Kleine, dauerhaft geführte Diff-Fläche in den Tauri-Capability-Dateien; klar definierte, testbare Kommandofläche; das Vertrauensmodell (Hauptprozess vertrauenswürdig, Webview minimal berechtigt) wird durchgesetzt. **Status:** beschlossen; **Pflicht vor produktivem Personal-Desktop-Betrieb**; noch nicht umgesetzt.

## Verweise

Primärdokumente: 18 DEV-2, 09 §3. Regeln: AV-21, AV-32. Entscheidungen: DEC-025, DEC-028.

---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-21
Zugehörige ADRs: ADR-0001, ADR-0004, ADR-0014
Verwandte DEC-Einträge: DEC-015, DEC-025, DEC-029; offen: DEC-D05, DEC-D06
---

# ADR-0008: Lokale Authentifizierung (Installationsgeheimnis + Session-Tokens)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Upstream-Server nutzt einen einzelnen optionalen Bearer-Key, auf Loopback default aus. Ein dauerhaftes Token im Webview-JavaScript wäre bei einem XSS-Fehler auslesbar. Gebraucht wird ein lokales Vertrauensmodell für SPA, Tauri, CLI und WebSockets ohne Kopplung der Fachmodule an Tauri. Zusatzbedingung: Die Browser-/Webview-WebSocket-API kann **keine eigenen `Authorization`-Header setzen** — die WebSocket-Authentifizierung braucht daher einen eigenen, technisch umsetzbaren Mechanismus.

## Entscheidung

1. **Installationsgeheimnis** ausschließlich im macOS-Keychain; lesen dürfen nur Backend und Tauri-Hauptprozess; Scope `personal:admin`; **die SPA erhält es niemals**.
2. **Kurzlebige Desktop-Session-Tokens je Desktop-Sitzung:** ausgestellt vom Backend an den Tauri-Hauptprozess (der sich mit dem Installationsgeheimnis authentisiert), an die SPA je Fenster übergeben; nur im Arbeitsspeicher; an die Sitzung/das Fenster gebunden; kurze Ablaufzeit mit Rotation (nur durch den Hauptprozess); widerrufbar beim App-Schließen; Scopes `personal:api`, `personal:ws`.
3. **CLI** nutzt das Installationsgeheimnis direkt aus dem Keychain.
4. **WebSocket-Authentifizierung per Einmal-Ticket (konkrete Ausgestaltung, DEC-029):** Die SPA authentifiziert HTTP-Anfragen mit ihrem Desktop-Session-Token und fordert vor jedem WebSocket-Aufbau über einen authentifizierten HTTP-Endpunkt ein **WebSocket-Ticket** an. Das Ticket ist kryptografisch zufällig, nur im Backend-Arbeitsspeicher gespeichert, **einmalig verwendbar**, höchstens **30 Sekunden** gültig und gebunden an Desktop-Session-ID, Fenster-ID, erlaubten Origin, Scope `personal:ws` und den vorgesehenen WebSocket-Endpunkt. Der Handshake übermittelt **nur dieses Ticket** — niemals das Installationsgeheimnis oder das Desktop-Session-Token. Der Server prüft das Ticket **vor `accept()`**, verbraucht es atomar und lehnt Wiederverwendung ab; Ticketwerte werden aus Zugriffslogs, Fehlern und Traces vollständig redigiert; fehlgeschlagener Handshake, Origin-Mismatch, Ablauf oder Wiederverwendung führen zur fail-closed-Ablehnung; App-Schließen oder Sitzungs-Widerruf invalidiert alle zugehörigen offenen Verbindungen und unbenutzten Tickets. Details: 09 §1. **Kein zusätzlicher ADR nötig — dies ist die Ausgestaltung dieses ADR.**
5. **Zusätzlich bleiben:** Origin-Allowlist, `/v1/personal/`-Präfix unter der Upstream-AuthMiddleware, genau ein Schreibprozess (serve.lock). Browserbetrieb bleibt deaktiviert; Dev-Betrieb nur über ausdrücklich aktivierten Entwicklungsmodus mit separatem kurzlebigem Token.
6. **Tauri-Härtung:** minimale Kommandofläche; keine breite `shell:allow-execute`-Berechtigung; kein `run_jarvis_command` im Personal-Betrieb (eigener ADR-0014, 18 DEV-2).

## Geprüfte Alternativen

- **Dauerhaftes Installations-Token in der SPA** — verworfen: XSS-Blast-Radius umfasst das Dauergeheimnis.
- **Manuell gepflegter API-Key (Upstream-Mechanik allein)** — verworfen: fail-open bei Config-Regeneration, keine Scopes, keine Widerrufbarkeit je Sitzung.
- **Vollständiger Tauri-Proxy für kritische Operationen** — verworfen: koppelte Fachmodule und React-Komponenten an Tauri und spaltete den CLI-Pfad; als optionale, transportneutrale R2-Zweitbestätigung weiterverfolgbar (DEC-D06).
- **`Authorization`-Header für Browser-WebSockets** — verworfen: von der Browser-/Webview-WebSocket-API technisch nicht setzbar.
- **Desktop-Session-Token als WebSocket-Query-Parameter** — verworfen: mehrfach verwendbar und log-leckanfällig; das Einmal-Ticket begrenzt Wert, Bindung und Lebensdauer auf das Minimum.

## Konsequenzen

Ein Webview-Kompromiss erbeutet höchstens ein kurzlebiges, scope-begrenztes Token bzw. ein bereits verbrauchtes Einmal-Ticket; Backend-Neustart invalidiert alle Sitzungen und Tickets; TTL-/Rotationswerte sind offen (DEC-D05); die Capability-Einengung ist eine geführte Upstream-Abweichung mit eigenem ADR (ADR-0014) und Test-Pflicht.

## Verweise

Primärdokument: 09 §1–§3. Regeln: AV-21. Entscheidungen: DEC-015, DEC-029.

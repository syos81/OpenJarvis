---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-20, AV-21
Zugehörige ADRs: ADR-0004, ADR-0008, ADR-0015
Verwandte DEC-Einträge: DEC-032
---

# ADR-0017: Anbindung des CredentialStore an den macOS-Keychain (DEC-D02)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

ADR-0004 legt fest, dass Geheimnisse produktiv ausschließlich im OS-Schlüsselbund liegen; offen war die technische Anbindung (DEC-D02). Mit dem ersten Fachmodul wird der CredentialStore-Kern materialisiert: Das Installationsgeheimnis der lokalen Authentifizierung (ADR-0008) liegt im Keychain und muss von **Python-Backend, CLI und Tauri-Hauptprozess** gelesen werden können. Der Audit zeigt, dass die Desktop-App bereits eine Keyring-Nutzung für Cloud-Schlüssel besitzt, während Backend und CLI bislang keine Keychain-Anbindung haben — eine gezielt zu schließende Implementierungslücke.

## Entscheidung

1. **Eine gemeinsame, providerneutrale `CredentialStore`-Schnittstelle** mit nativer macOS-Keychain-Nutzung als produktiver Implementierung; `InMemoryCredentialStore` ausschließlich für Tests.
2. **Gemeinsamer, dokumentierter Service-/Account-Namensraum:** Python-Backend, CLI und Tauri-Hauptprozess verwenden dieselben Keychain-Service- und Account-Bezeichner, damit alle drei Prozesse dieselben Einträge sehen. Der Namensraum wird in der Modulunterlage bzw. in 09 dokumentiert und ist Bestandteil der Contract-Suite.
3. **Geeignete `keyring`-Bibliotheken dürfen hinter dem Vertrag eingesetzt werden**; die Wahl bleibt austauschbar und ist kein Bestandteil der Fachlogik. Zwingend ist ein explizit konfiguriertes macOS-Backend (kein stiller Fallback auf einen unsicheren oder flüchtigen Speicher).
4. **Geheimnisse dürfen niemals an die React-SPA weitergegeben werden** (AV-21, ADR-0008, ADR-0015): Die SPA erhält ausschließlich kurzlebige Session-Tokens und WebSocket-Einmal-Tickets.
5. Es gelten unverändert die Regeln aus 09 §4: zweckgebundene Einzelauflösung je Adapter/Konto/Zweck, keine Secrets in SQLite, Dateien, `os.environ`-Broadcasts, Logs, Traces oder normalen Backups; Secret-Export nur als R2-Operation; normalisierte Fehlerzustände für fehlenden, gesperrten oder verweigerten Zugriff (fail-closed im Bootstrap).
6. Linux erhält später denselben Vertrag über die standardisierte Secret-Service-Schnittstelle; der Server-Fall bleibt offen (DEC-D13).

## Geprüfte Alternativen

- **Eigene, direkte Security-Framework-Bindung** — verworfen für den Erstschritt: höherer Eigenaufwand ohne Sicherheitsgewinn gegenüber einer etablierten Bibliothek; bleibt hinter dem Vertrag jederzeit nachrüstbar.
- **Nur die vorhandene Tauri-Keyring-Nutzung** — verworfen: koppelte Backend- und CLI-Betrieb an die Desktop-App (bereits in ADR-0004 abgelehnt).
- **Getrennte Namensräume je Prozess** — verworfen: erzeugte doppelte Einträge und divergierende Wahrheiten für dasselbe Geheimnis.
- **Dateibasierter Store als Fallback** — durch ADR-0004 ausgeschlossen.

## Konsequenzen

Ein einziger, testbarer Zugriffsweg für alle drei Prozesse; die Contract-Suite (InMemory + macOS-Keychain, inkl. gesperrt/verweigert/fehlend) sichert das Verhalten ab. Der dokumentierte Namensraum wird Teil der Modulunterlage und darf nur per ADR geändert werden.

## Verweise

Primärdokumente: 09 §4, 09 §1, 17 (DEC-D02). Regeln: AV-20, AV-21. Entscheidung: DEC-032.

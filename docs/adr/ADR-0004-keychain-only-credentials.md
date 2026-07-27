---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-20
Zugehörige ADRs: ADR-0008, ADR-0010
Verwandte DEC-Einträge: DEC-010; offen: DEC-D02, DEC-D13
---

# ADR-0004: Keychain-only CredentialStore

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Adapter benötigen Zugangsdaten (App-Passwörter, API-Keys, Broker-Credentials). Der Audit belegte Schwächen der Upstream-Mechanismen (`credentials.toml` mit Export aller Tokens nach `os.environ` an alle Subprozesse und ohne TOML-Escaping; ein unverdrahteter „Vault" mit Schlüssel neben dem Ciphertext). Die kanonische Datenbank ist ausdrücklich secret-frei.

## Entscheidung

1. Providerneutraler **CredentialStore-Vertrag**; produktive Speicherung **ausschließlich im OS-Schlüsselbund**: `MacOSKeychainCredentialStore` (macOS), später `LinuxSecretServiceCredentialStore`; `InMemoryCredentialStore` nur für Tests.
2. Die Implementierung ist **nicht an Tauri gekoppelt**: Backend, CLI und Desktop nutzen denselben Vertrag; eine vorhandene Tauri-Keyring-Implementierung darf dahinter gekapselt werden; Fachmodule kennen Tauri nicht.
3. Fachmodule speichern nur **CredentialReference**-Werte; Auflösung ist zweckgebunden je Adapter, Konto und Zweck; ein Adapter erhält nur das konkret angeforderte Secret.
4. Regeln: keine Secrets in SQLite/TOML/JSON; kein `os.environ`-Broadcast; keine Secrets in Logs, Traces, Fehlermeldungen oder normalen Backups; Speichern/Lesen/Ersetzen/Löschen/Rotation unterstützt; normalisierte Fehlerzustände (fehlend/gesperrt/verweigert); Secret-Export nur als separate R2-Operation.
5. **Kein dateibasierter Credential-Store als produktiver Fallback**; Upstream-`credentials.toml` wird für neue Module nicht verwendet.

## Geprüfte Alternativen

- **Eigener 0600-Datei-Store je Modul** — verworfen (Eigentümer-Entscheid): schwächer als der Schlüsselbund; die fehlende Backend-/CLI-Keychain-Anbindung ist eine zu schließende Implementierungslücke, kein Grund für Dateispeicher.
- **Upstream-`credentials.toml`** — verworfen: erbt Env-Broadcast und Escaping-Schwäche.
- **Nur Tauri-Keyring** — verworfen: koppelte Headless-/CLI-Betrieb an die Desktop-App.

## Konsequenzen

Unbeaufsichtigter Home-Server-Betrieb braucht später eine eigene Secret-Store-Entscheidung (DEC-D13); die konkrete Keychain-Bindungstechnik ist offen (DEC-D02); Keychain-Fehlzustände führen im Bootstrap zu fail-closed (04 §1).

## Verweise

Primärdokument: 09 §4. Regeln: AV-20.

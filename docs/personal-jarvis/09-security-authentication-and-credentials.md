---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-20, AV-21
Zugehörige ADRs: ADR-0004, ADR-0008, ADR-0014
Verwandte DEC-Einträge: DEC-010, DEC-015, DEC-025, DEC-029
---

# 09 — Sicherheit: Lokale Authentifizierung und Credentials

## §1 Lokale Authentifizierung

- **Installationsgeheimnis:** dauerhaft, ausschließlich im macOS-Keychain; lesen dürfen nur das Backend und der Tauri-Hauptprozess. **Die SPA erhält es niemals.** Scope: `personal:admin` (Session-Ausstellung, Rotation, CLI-Vollzugriff). Erzeugt vom Backend beim ersten Personal-Start; Rotation über einen Admin-Befehl (Backend lädt neu, Clients holen es erneut).
- **Desktop-Session-Tokens je Desktop-Sitzung:** Der Tauri-Hauptprozess authentisiert sich mit dem Installationsgeheimnis am Backend (`POST /v1/personal/auth/session`) und erhält ein zufälliges, kurzlebiges Session-Token, das er der SPA pro Fenster per `invoke` übergibt. Eigenschaften: **nur im Arbeitsspeicher** (Backend hält eine In-Memory-Token-Tabelle; Neustart invalidiert alle); gebunden an Sitzungs-/Fenster-ID; kurze Ablaufzeit mit Rotation (Erneuerung ausschließlich durch den Tauri-Hauptprozess, nie durch die SPA); **widerrufen beim App-Schließen** (Exit-Hook + TTL-Ablauf); begrenzte Scopes `personal:api` und `personal:ws`. Ein XSS in der Webview erbeutet damit höchstens ein kurzlebiges, widerrufbares, scope-begrenztes Token — nie das Installationsgeheimnis. TTL-/Rotationswerte: DEC-D05.
- **CLI:** nutzt das Installationsgeheimnis direkt aus dem Keychain (vertrauenswürdiger lokaler Prozess).
- **Transport und Prüfung (HTTP):** Alle `/v1/personal/*`-Routen verlangen ein gültiges Token; das Präfix liegt unter `/v1/` und erbt damit zusätzlich die Upstream-AuthMiddleware. Zustandsändernde Routen prüfen zusätzlich eine **Origin-Allowlist** (`tauri://…`, konfigurierte Dev-Origins). Keine Cookies — klassisches CSRF entfällt; die Origin-Prüfung ist die zweite Schicht.
- **WebSocket-Authentifizierung (Einmal-Ticket-Verfahren, DEC-029):** Die Browser-/Webview-WebSocket-API kann keine eigenen `Authorization`-Header setzen; deshalb gilt verbindlich: (a) Die SPA authentifiziert normale HTTP-Anfragen mit ihrem Desktop-Session-Token. (b) Vor jedem WebSocket-Aufbau fordert sie über einen so authentifizierten HTTP-Endpunkt ein **WebSocket-Ticket** an. (c) Das Ticket ist kryptografisch zufällig, nur im Backend-Arbeitsspeicher gespeichert, **einmalig verwendbar**, höchstens **30 Sekunden** gültig und gebunden an Desktop-Session-ID, Fenster-ID, erlaubten Origin, Scope `personal:ws` und den vorgesehenen WebSocket-Endpunkt. (d) Der Handshake übermittelt **nur dieses Einmal-Ticket** — niemals das Installationsgeheimnis und niemals das Desktop-Session-Token. (e) Der Server prüft das Ticket **vor `accept()`**, verbraucht es atomar und lehnt jede Wiederverwendung ab. (f) Ticketwerte werden aus Zugriffslogs, Fehlermeldungen und Traces vollständig redigiert. (g) Fehlgeschlagener Handshake, Origin-Mismatch, Ablauf oder Wiederverwendung ⇒ **fail-closed**-Ablehnung der Verbindung. (h) App-Schließen oder Widerruf der Desktop-Sitzung invalidiert alle dazugehörigen offenen Verbindungen und unbenutzten Tickets.
- **Browserbetrieb:** standardmäßig deaktiviert (kein Token-Weg). **Dev-Browserbetrieb** nur über ausdrücklich aktivierten Entwicklungsmodus mit separatem, ebenso kurzlebigem Dev-Token — nie das Installationsgeheimnis.
- **Portwechsel / Zweitprozess:** Tokens und Tickets sind portunabhängig; Port-Discovery über `personal/serve.lock`; ein zweiter Serverprozess ist durch die exklusive Sperre ausgeschlossen (07 §5).

## §2 Geprüfte Alternative: Tauri-Proxy

Ein vollständiger Tauri-Proxy für kritische Operationen wurde geprüft und verworfen: Er würde Fachmodule und React-Komponenten an Tauri koppeln (verboten, AV-6/AV-9) und den CLI-Pfad spalten (AV-35). **Optionale additive Härtung stattdessen:** R2-Freigaben können zusätzlich einen nativen OS-Bestätigungsdialog verlangen — realisiert als dünne, feature-geschaltete Dekoration eines transportneutralen `ApprovalClient`-Vertrags; Module und Komponenten bleiben davon unabhängig (DEC-D06, nicht beschlossen).

## §3 Tauri-Kommandorechte

Personal nutzt eine minimale Kommandofläche (API-Base/Session-Token-Bereitstellung, Dialoge). **Keine breite `shell:allow-execute`-Berechtigung für die Webview** und kein `run_jarvis_command` im Personal-Betrieb; die Capability-Einengung auf Sidecar-Scope ist Pflicht vor produktivem Personal-Desktop-Betrieb und wird als Upstream-Abweichung mit eigenem ADR geführt (18 DEV-2, **ADR-0014**, DEC-025).

## §4 CredentialStore

**Vertrag** mit produktiver Implementierung ausschließlich über den OS-Schlüsselbund (AV-20, ADR-0004):

```
CredentialStore
├── MacOSKeychainCredentialStore   (produktiv, macOS)
├── später: LinuxSecretServiceCredentialStore
└── InMemoryCredentialStore        (ausschließlich automatisierte Tests)
```

- Für macOS ist der Apple-Schlüsselbund die **einzige produktive Wahrheit** für Zugangsdaten. Die Implementierung ist **nicht an die Tauri-Oberfläche gekoppelt**: Python-Backend, CLI und native Desktop-App verwenden denselben Vertrag; der Zugriff erfolgt über eine eng begrenzte native Security-Framework-/Keychain-Integration (Technik: DEC-D02). Falls die vorhandene Tauri-Keyring-Implementierung wiederverwendbar ist, wird sie hinter diesem Vertrag gekapselt; Fachmodule kennen Tauri nicht.
- Fachmodule speichern ausschließlich **CredentialReference**-Werte (zweckgebunden je Adapter, Konto, Zweck) — niemals das Geheimnis selbst.
- **Operationen:** Speichern, Lesen, Ersetzen, Löschen, Rotation. **Auflösung** (`resolve(reference, purpose)`) liefert genau das eine angeforderte Secret für die Dauer des Aufrufs; kein Adapter erhält pauschal alle Zugangsdaten.
- **Normalisierte Fehlerzustände** für fehlenden, gesperrten oder verweigerten Keychain-Zugriff (fail-closed im Bootstrap, 04 §1 Schritt 5).
- **Verbindliche Regeln:** keine Secrets in SQLite; keine Secrets in TOML oder JSON; kein Export aller Secrets nach `os.environ`; keine Secrets in Logs, Traces, Fehlermeldungen oder Backups; Secrets werden standardmäßig nicht mit normalen Datenexporten gesichert; ein separater Secret-Export existiert nur als ausdrücklich freigabepflichtige **R2**-Operation (13 §6); Test-Doubles nur in Tests.
- **Kein dateibasierter Credential-Store als produktiver Fallback.** Upstream-`credentials.toml` wird für neue Module nicht verwendet (02 §2.3).
- Für Linux wird derselbe Vertrag später über die standardisierte Secret-Service-Schnittstelle umgesetzt. Für einen unbeaufsichtigten Home-Server wird der geeignete Secret Store separat entschieden (DEC-D13); diese spätere Entscheidung reduziert die macOS-Desktop-Architektur nicht auf einen unsicheren Dateispeicher.

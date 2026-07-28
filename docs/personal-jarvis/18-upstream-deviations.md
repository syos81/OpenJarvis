---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-25, AV-32, AV-34 (Integrationspunkt-Anteil)
Zugehörige ADRs: ADR-0001, ADR-0011, ADR-0013, ADR-0014, ADR-0015
Verwandte DEC-Einträge: DEC-006, DEC-025, DEC-026, DEC-027, DEC-028, DEC-041
---

# 18 — Upstream-Abweichungsliste

## §1 Regeln

1. Diese Liste ist **abschließend**: Es gibt keine bewusste Abweichung von Upstream-Dateien außerhalb dieser Liste (AV-1, AV-32).
2. **Jede bewusste Upstream-Abweichung besitzt einen eigenen akzeptierten ADR — ausnahmslos** (DEC-027): DEV-1 → **ADR-0013**, DEV-2 → **ADR-0014**, DEV-3 → **ADR-0001**, DEV-4 und DEV-5 → **ADR-0015**. Jede künftige Abweichung erfordert **vor Umsetzung** einen freigegebenen ADR und einen Eintrag in dieser Liste.
3. Jede Abweichung erhält bei Umsetzung mindestens einen absichernden Test.
4. Bei jeder selektiven Upstream-Übernahme (02 §3) wird diese Liste erneut geprüft (Konflikt-Re-Check).
5. Additive neue Dateien (Personal-Namensraum, dieser Doku-Korpus, additive Tests/Workflows) gelten **nicht** als Abweichung.

## §2 Abweichungen

### DEV-1 — Telemetrie-Default

- **Bereich:** externe Analytics (PostHog), Upstream-Konfigurationsdefault.
- **Betroffen:** `src/openjarvis/core/config.py` (`AnalyticsConfig.enabled`, eine Zeile).
- **Abweichung:** Code-Default `True` → `False`; zusätzlich `[analytics] enabled = false` in allen eigenen Presets; Leaderboard bleibt aus (kein Build-Key); `install.sh` ist kein Installationsweg dieses Forks (Installer-Beacon entfällt dadurch). Lokale technische Metriken bleiben erhalten.
- **Begründung:** Privacy-Default eines persönlichen Assistenten; fail-safe gegenüber Config-Regeneration (Audit-Befund: generierte Config enthält keine `[analytics]`-Sektion; dokumentierter Opt-out-Befehl existiert upstream nicht).
- **Autorisierung:** **ADR-0013**, AV-25, DEC-006, DEC-027. **Test-Pflicht:** Unit-Test „Default ist False". **Status:** beschlossen; Umsetzung folgt mit der ersten Code-Phase (noch nicht umgesetzt).

### DEV-2 — Tauri-Capability-Härtung

- **Bereich:** Desktop-Webview-Rechte.
- **Betroffen:** `frontend/src-tauri/capabilities/*` (Einengung `shell:allow-execute` auf Sidecar-Scope) sowie die Nichtnutzung/Sperrung von `run_jarvis_command` im Personal-Betrieb.
- **Begründung:** Audit-Befund: breite Shell-Rechte + beliebige CLI-Subkommandos aus der Webview; unvereinbar mit dem Session-Token-Vertrauensmodell (09).
- **Autorisierung:** **ADR-0014**, Baseline v3 (09 §3), DEC-025, DEC-028. **Test-Pflicht:** Capability-Regressionstest (erlaubte Kommandofläche) + Desktop-Regressionstest. **Status:** beschlossen; **Pflicht vor produktivem Personal-Desktop-Betrieb**; noch nicht umgesetzt.

### DEV-3 — `serve`-Integrationspunkt

- **Bereich:** Anbindung von Personal an `jarvis serve`.
- **Betroffen:** genau ein bewachter Aufruf (`personaljarvis.attach(app)`) in der Upstream-App-Factory bzw. im Lifespan, hinter Feature-Schalter und `try/except ImportError` (04 §4).
- **Begründung:** `jarvis serve` bleibt der produktive lokale Serverpfad; die Integration muss additiv, abschaltbar und upstream-neutral sein.
- **Autorisierung:** **ADR-0001**, AV-34, DEC-026. **Test-Pflicht:** zwei Tests (aktiviert ⇒ Personal-Routen vorhanden; deaktiviert/fehlend ⇒ App identisch zu Upstream). **Status:** beschlossen; noch nicht umgesetzt.

### DEV-4 — Personal-Registrierungspunkte in Frontend und Desktop

- **Bereich:** SPA-Routing/Navigation und Tauri-Kommandofläche.
- **Betroffen:** `frontend/src/App.tsx` (eine readiness-gesteuerte Modul-Route), `frontend/src/components/Sidebar/Sidebar.tsx` (ein Navigationseintrag, sichtbar nur bei Readiness), `frontend/src-tauri/src/lib.rs` (minimal erforderliche sichere Kommandos zur Beschaffung des kurzlebigen Desktop-Session-Tokens; API-Basis-Ermittlung besteht bereits).
- **Umfangsgrenzen (verbindlich):** ausschließlich diese drei Punkte; **keine Geheimnisse erreichen die React-SPA** (nur kurzlebige Session-Tokens und WebSocket-Einmal-Tickets, 09 §1); **kein zweiter fachlicher Ausführungspfad** — alle Mutationen laufen über den ApplicationCommandBus (AV-35); keine Tauri-Abhängigkeit von Fachmodulen oder React-Komponenten (AV-6/AV-9); kein dynamisches Nachladen von Frontend-Code (14 §2).
- **Begründung:** Die native Desktop-UI ist je Modul Pflicht (AV-9); Routing und Navigation sind upstream zentral definiert, und das Vertrauensmodell aus ADR-0008 erfordert eine Token-Bereitstellung durch den Tauri-Hauptprozess.
- **Autorisierung:** **ADR-0015**, AV-9/AV-21, DEC-041. **Test-Pflicht:** Navigationseintrag ohne Readiness unsichtbar · App identisch ohne Personal (gemeinsam mit DEV-3) · Capability-Regressionstest der erlaubten Kommandofläche · Nachweis, dass kein dauerhaftes Geheimnis in der SPA verfügbar ist. **Status:** beschlossen; noch nicht umgesetzt.

### DEV-5 — Additive Personal-Dependency-Group

- **Bereich:** Python-Abhängigkeitsauflösung des Source-Checkouts.
- **Betroffen:** `pyproject.toml` — ausschließlich eine additive Gruppe `[dependency-groups] personal = [...]`.
- **Umfangsgrenzen (verbindlich):** **bestehende Standard-Abhängigkeiten und Extras bleiben unverändert**; das bestehende `openjarvis`-Paket bleibt im Wheel vollständig und unverändert enthalten.
- **Präzisierung 2026-07-28 (Gate A):** Die ursprüngliche Formulierung „keine Änderung an `[tool.hatch.build.targets.wheel]`“ ging davon aus, der Personal-Betrieb liefe ausschließlich aus dem Source-Checkout. Der Eigentümer hat für Gate A ausdrücklich verlangt, dass das produktive Wheel `personaljarvis` enthält und der Import aus einer isolierten Installation **ohne** Repository-`src`-Pfad nachgewiesen wird. Umgesetzt ist deshalb die kleinstmögliche additive Änderung: `packages = ["src/openjarvis", "src/personaljarvis"]`. `force-include`, Extras und Standard-Abhängigkeiten bleiben unberührt; der Nachweis erfolgt über Wheel-Inhalts- und isolierte Importtests.
- **Begründung:** Das Personal-Paket benötigt eigene Abhängigkeiten (u. a. Keychain-Anbindung), ohne die Auflösung oder Auslieferung von OpenJarvis zu verändern.
- **Autorisierung:** **ADR-0015**, AV-1, DEC-041. **Test-Pflicht:** Nachweis, dass die Standard-Auflösung ohne die Personal-Gruppe unverändert bleibt. **Status:** beschlossen; noch nicht umgesetzt.

## §3 Ausdrücklich keine Abweichungen

`mkdocs.yml` bleibt unverändert (00 §4). Upstream-Workflows, -Tests und -Quellcode werden außer DEV-1–DEV-3 nicht berührt; Hygiene-Funde des Audits (77-MB-Binary, totes `desktop/`-Verzeichnis, Doku-Drift) bleiben ohne gesonderte Freigabe unangetastet (02 §2.4).

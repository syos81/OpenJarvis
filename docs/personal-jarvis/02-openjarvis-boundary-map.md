---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-25, AV-27, AV-32
Zugehörige ADRs: ADR-0011, ADR-0013, ADR-0014
Verwandte DEC-Einträge: DEC-006, DEC-007, DEC-009, DEC-025, DEC-026
---

# 02 — OpenJarvis-Bestandskarte und Upstream-Grenze

## §1 Baseline-Fakten

- Fork: `git@github.com:syos81/OpenJarvis.git` (origin) von `https://github.com/open-jarvis/OpenJarvis.git` (upstream).
- Arbeits-Branch: `jarvis/rebuild-v1`; eingefrorene Baseline: Commit `a7c31e89…`, Tag `openjarvis-baseline-2026-07-27` (lokal und auf origin, annotiert).
- Grundlage der Einordnung ist der Architektur-Audit vom 2026-07-27 (Chat-Abschlussbericht); dessen für die Architektur maßgebliche Ergebnisse sind in diesem Korpus materialisiert.

## §2 Bestandskarte (vier Kategorien)

### 2.1 Unverändert verwenden

`core/` (Registry, Typen, EventBus, Paths) · `engine/` samt Discovery (Ollama-first, Cloud optional) · `server/`-Kern inkl. AuthMiddleware (Bearer, Bind-Safety) und `jarvis serve` · `cli/`-Gerüst · `tools/storage/` als **abgeleiteter** Suchindex · `speech/` (STT lokal-first) · `scheduler/` · `traces/`, lokale `telemetry/` · Rust-Workspace + maturin-Build · Tauri-Shell, React-SPA, Desktop-Release-Train · Presets-Mechanik · Evals (ruhend).

### 2.2 Über Adapter kapseln (ausschließlich hinter dem OJRA)

`SystemBuilder` / `JarvisSystem` / `QueryOrchestrator`, Upstream-EventBus, Upstream-Scheduler, Memory-Backends, Engine-Zugriff, Tool-Registrierung — kein Fachmodul importiert Upstream-Interna (AV-6/AV-7; Mechanik in 04). Ebenfalls in der Adapterschicht gekapselt: die **macOS-native Bridge** (EventKit/CNContactStore, 08 §4).

### 2.3 Deaktiviert bleiben

PostHog-Analytics (Code-Default → `False`; Abweichung DEV-1 in 18) · Installer-Beacon (`install.sh` ist kein Installationsweg dieses Forks) · Mining/„Pearl" · Node-Zusatz-Bridges (WhatsApp-Baileys, Claude-Code-Runner; als ausgeliefert nicht lauffähig) · Dritt-Skill-Installationen (bis Verifikation aktiv ist) · sämtliche Upstream-Channels (initial keiner aktiv) · `spec_search` und Hybrid-Forschungsagenten (ruhend) · Upstream-`credentials.toml` für neue Module.

### 2.4 Später ersetzen / absichern

Jeweils erst, wenn ein Modul den betroffenen Pfad produktiv braucht (AV-33):

- OAuth-Flows → ausschließlich eigener Flow mit `state` + PKCE + exakter Redirect-Prüfung; der auditierte Upstream-Flow wird nicht verwendet.
- `code_interpreter` / `shell_exec` → nur mit Sandbox + Bestätigung per Konfiguration, falls Code-Ausführung je aktiviert wird.
- Tauri-Capability `shell:allow-execute` → Einengung auf Sidecar-Scope; kein `run_jarvis_command` im Personal-Betrieb (**Pflicht vor produktivem Personal-Desktop-Betrieb**; Abweichung DEV-2 in 18).
- Dateirechte (chmod) der Upstream-Datenbanken.
- Upstream-ApprovalStore (wird nicht genutzt; der Personal-Approval-Kern ist eigenständig, 10).
- SSRF-Prüfung für `browser_navigate`; Rate-Limiter als Middleware — nur bei produktiver Nutzung der betroffenen Upstream-Pfade.
- Hygiene (77-MB-Binary, totes `desktop/`-Verzeichnis): bewusst liegen gelassen; keine Bereinigung ohne gesonderte Freigabe.

## §3 Upstream-Strategie (selektive Integration)

Die Baseline bleibt eingefroren; **keine automatischen Rebases, keine Pauschal-Merges** (ADR-0011). Übernommen werden Upstream-Änderungen ausschließlich selektiv nach diesen Kriterien:

1. Sicherheitsfixes,
2. Datenverlust- oder Korruptionsfixes,
3. Fehlerbehebungen in von uns tatsächlich genutzten Komponenten,
4. wichtige macOS-, Rust-, Tauri- oder Inferenzfixes.

**Prozess je Übernahme:** Prüfung (Audit des Patches) → Tests → eigener Commit → Dokumentationseintrag; zusätzlich Re-Check der Abweichungsliste (AV-32, 18). Generische eigene Fixes dürfen upstream angeboten werden.

## §4 Verweise

Abweichungsdetails: 18. Toolchain-Matrix: 15 §6 (AV-29). Kompositionsgrenze: 04.

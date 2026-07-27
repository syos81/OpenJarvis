---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-6, AV-9, AV-21, AV-32, AV-35
Zugehörige ADRs: ADR-0001, ADR-0008, ADR-0014
Verwandte DEC-Einträge: DEC-040, DEC-041
---

# ADR-0015: Minimale Personal-Integrationspunkte in Frontend, Desktop und Packaging (DEV-4, DEV-5)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Die Architektur verlangt eine vollständige native Desktop-UI je Fachmodul (AV-9, 14) und einen additiven Personal-Namensraum (AV-1). Der Code-Audit zum ersten Fachmodul „Kontakte" hat drei unvermeidbare Berührungspunkte mit Upstream-Dateien belegt, die keine der bereits genehmigten Abweichungen DEV-1 bis DEV-3 abdeckt:

1. Die SPA-Routen sind zentral in `frontend/src/App.tsx` definiert; die Navigation ist ein Array in `frontend/src/components/Sidebar/Sidebar.tsx`.
2. Das Desktop-Vertrauensmodell (ADR-0008) verlangt, dass der Tauri-Hauptprozess das Installationsgeheimnis aus dem Keychain liest und der SPA nur kurzlebige Session-Tokens bereitstellt. Der Bestand kennt zwar `get_api_base`, aber **kein** Token-Provisioning aus Rust.
3. Für das Personal-Paket werden zusätzliche Python-Abhängigkeiten benötigt, ohne die Standard-Abhängigkeiten oder das Upstream-Wheel-Packaging zu verändern.

Beide Abweichungen wurden vom Eigentümer am 2026-07-27 genehmigt und sind als **DEV-4** und **DEV-5** in der Abweichungsliste (18) geführt; dieser ADR ist ihr Entscheidungsnachweis (AV-32).

## Entscheidung

### DEV-4 — Frontend- und Desktop-Registrierungspunkte

Der Umfang ist **abschließend** auf drei Punkte begrenzt:

1. **Eine readiness-gesteuerte Modul-Route** in `frontend/src/App.tsx` (Kontakte; künftige Module analog über dieselbe Personal-Registry).
2. **Ein Navigationseintrag** in `frontend/src/components/Sidebar/Sidebar.tsx`, dessen Sichtbarkeit an die Laufzeit-Readiness gekoppelt ist (14 §2): sichtbar nur, wenn das Modul kompiliert **und** in einem erlaubten Lifecycle-Zustand ist.
3. **Minimal erforderliche sichere Tauri-Kommandos** in `frontend/src-tauri/src/lib.rs` — ausschließlich zur Beschaffung des kurzlebigen Desktop-Session-Tokens (der Hauptprozess liest das Installationsgeheimnis aus dem Keychain und fordert beim Backend ein Session-Token an) sowie zur bestehenden API-Basis-Ermittlung.

**Verbindliche Grenzen:** Keine Geheimnisse erreichen die React-SPA — die SPA erhält ausschließlich kurzlebige, scope-begrenzte Session-Tokens und WebSocket-Einmal-Tickets (ADR-0008, 09 §1). Es entsteht **kein zweiter fachlicher Ausführungspfad**: alle Mutationen laufen über den ApplicationCommandBus (AV-35); Tauri-Kommandos führen keine Fachlogik aus. Fachmodule und React-Komponenten bleiben von Tauri-internen Details unabhängig (AV-6). Die Capability-Fläche bleibt durch ADR-0014 eingeengt.

**Test-Pflichten:** (a) Navigationseintrag ist ohne Readiness nicht sichtbar; (b) Personal deaktiviert oder nicht gebaut ⇒ Upstream-App identisch (gemeinsam mit dem DEV-3-Test); (c) Capability-Regressionstest der erlaubten Kommandofläche (ADR-0014); (d) Nachweis, dass kein dauerhaftes Geheimnis in der SPA verfügbar ist.

### DEV-5 — Additive Personal-Dependency-Group

In `pyproject.toml` wird **ausschließlich** eine additive PEP-735-Gruppe `[dependency-groups] personal = [...]` ergänzt. **Bestehende Standard-Abhängigkeiten, Extras und das Upstream-Wheel-Packaging (`[tool.hatch.build.targets.wheel]`) bleiben unverändert.** Der Personal-Betrieb läuft aus dem Source-Checkout (AV-29), sodass keine Wheel-Änderung nötig ist.

**Test-Pflicht:** Ein Test bzw. Prüfschritt belegt, dass die Standard-Auflösung (`uv sync` ohne die Personal-Gruppe) unverändert bleibt.

## Geprüfte Alternativen

- **Separate zweite Web-UI für Personal** — verworfen: dauerhafte zweite Shell (Auth, Navigation, Packaging), Verlust der Desktop-Integration, widerspricht „schlank" und AV-9.
- **Dynamisches Nachladen von Modul-Frontends zur Laufzeit** — verworfen: 14 §2 verbietet das Nachladen ungeprüften Frontend-Codes; Build-time-Registrierung ist die beschlossene Form.
- **Token-Beschaffung ohne Tauri-Kommando (Datei/Umgebungsvariable)** — verworfen: würde ein Geheimnis außerhalb des Keychains ablegen (Verstoß gegen AV-20) oder es der SPA dauerhaft zugänglich machen.
- **Vollständiger Tauri-Proxy für Fachoperationen** — bereits in ADR-0008 verworfen: zweiter Ausführungspfad und Tauri-Kopplung.
- **Vendoring der Personal-Abhängigkeiten oder Aufnahme in die Kern-Dependencies** — verworfen: verändert Upstream-Auflösung und Wheel-Inhalt; die additive Gruppe ist der minimale Eingriff.

## Konsequenzen

Drei klar begrenzte, testgesicherte Berührungspunkte statt einer parallelen Infrastruktur; die Diff-Fläche gegenüber Upstream bleibt klein und wird bei jeder selektiven Übernahme erneut geprüft (AV-32, 18 §1 Nr. 4). Künftige Fachmodule nutzen dieselben Registrierungspunkte, ohne dass neue Abweichungen entstehen.

## Verweise

Primärdokumente: 18 DEV-4/DEV-5, 14 §2, 09 §1. Regeln: AV-1, AV-6, AV-9, AV-21, AV-32, AV-35. Entscheidungen: DEC-040, DEC-041.

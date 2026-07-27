---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-6, AV-7, AV-31, AV-34
Zugehörige ADRs: ADR-0005, ADR-0011
Verwandte DEC-Einträge: DEC-003, DEC-026
---

# ADR-0001: Personal-Runtime-Fassade (PJR-Ports + OpenJarvisRuntimeAdapter)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Architektur-Audit belegte drei parallele, inkonsistente Kompositionswege in OpenJarvis (SystemBuilder/SDK, Hand-Verdrahtung in `ask`/`chat`/`serve`, Server) mit messbaren Verhaltensunterschieden; die deklarierte Composition-Root `SystemBuilder`→`JarvisSystem`→`QueryOrchestrator` ist upstream ungetestet. Fachmodule dürfen nicht von diesen wechselnden Interna abhängen; zugleich soll der Core minimal verändert bleiben und `jarvis serve` der produktive Serverpfad sein.

## Entscheidung

1. Fachmodule kennen ausschließlich die **PersonalJarvisRuntime** — ein Bündel kleiner, einzeln versionierter Ports (ModelPort, MemoryIndexPort, ToolRegistrationPort, EventPort, SchedulerPort, ConfigurationPort, RuntimeHealthPort); Module erhalten nur benötigte Ports per Constructor Injection (04 §2).
2. Der **OpenJarvisRuntimeAdapter** ist die einzige Upstream-Brücke; er nutzt intern zunächst SystemBuilder/JarvisSystem/QueryOrchestrator; keine Upstream-Typen überqueren Port-Grenzen.
3. Es gibt genau eine **PersonalCompositionRoot** je Prozess mit definierter Start-/Stop-Reihenfolge und fail-closed-Verhalten (04 §1).
4. Die Integration in `jarvis serve` ist genau **ein bewachter Aufruf** (`personaljarvis.attach(app)`, feature-geschaltet, `try/except ImportError`) — geführt als Abweichung DEV-3 (18 §2) mit Test-Pflicht. Kein Umbau von `serve`, `ask` oder `chat`.

## Geprüfte Alternativen

- **Direkte Modulabhängigkeit auf SystemBuilder** — verworfen: ungetestete, wechselnde Interna; jede Upstream-Änderung schlüge auf alle Module durch.
- **Nachbau der CLI-Verdrahtung je Modul** — verworfen: verewigt die auditierte Duplikation und Drift.
- **Vorab-Refactor der Upstream-Kompositionswege** — verworfen: horizontale Core-Großbaustelle vor dem ersten Modul; widerspricht minimaler Core-Veränderung.
- **Ein einzelnes großes Runtime-Interface** — verworfen: God-Interface-Risiko; stattdessen Port-Bündel mit ADR-Pflicht für Erweiterungen.

## Konsequenzen

Fachmodule bleiben von Upstream-Reparaturen/-Austausch unberührt (Contract-Tests fixieren die Port-Semantik); eine kleine, dauerhaft zu pflegende Fassadenschicht entsteht; der Integrationspunkt ist die einzige `serve`-Berührung und wird doppelt getestet (aktiv/inaktiv).

## Verweise

Primärdokument: 04. Betroffen: 03, 05, 18 (DEV-3). Regeln: AV-6, AV-7, AV-31, AV-34.

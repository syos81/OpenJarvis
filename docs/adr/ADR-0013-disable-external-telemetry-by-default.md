---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-25, AV-32
Zugehörige ADRs: ADR-0011
Verwandte DEC-Einträge: DEC-006, DEC-027
---

# ADR-0013: Externe Telemetrie im Fork standardmäßig deaktiviert (DEV-1)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Der Architektur-Audit belegte: PostHog-Telemetrie ist upstream opt-out und **standardmäßig aktiv** (`AnalyticsConfig.enabled = True`, hartkodierter IP-basierter Host und Projekt-Key), der Shell-Installer sendet einen Install-Beacon **ohne jede Opt-out-Möglichkeit**, die generierte `config.toml` enthält keine `[analytics]`-Sektion, und der dokumentierte Opt-out-Befehl existiert nicht. Für einen persönlichen Assistenten mit Local-first-Anspruch (AV-5) ist ein Privacy-Default erforderlich, der nicht von Konfigurationsdisziplin abhängt. Diese Abweichung ist als **DEV-1** in der Abweichungsliste (18) geführt; dieser ADR ist ihr eigener Entscheidungsnachweis — die allgemeine Baseline-Freigabe allein ersetzt keinen ADR (DEC-027).

## Entscheidung

1. **PostHog bzw. externe Analytics sind im Fork standardmäßig aus:** Code-Default `AnalyticsConfig.enabled = False` (Ein-Zeilen-Abweichung in `src/openjarvis/core/config.py`).
2. **Eigene Presets setzen zusätzlich `[analytics] enabled = false`** (Gürtel und Hosenträger).
3. **Leaderboard bleibt aus** (kein Supabase-Build-Key wird gesetzt).
4. **`install.sh` ist kein Installationsweg dieses Forks** — der bedingungslose Installer-Beacon entfällt dadurch vollständig.
5. **Lokale technische Metriken bleiben möglich** (`telemetry/`-Subsystem, SQLite, ohne externen Versand).
6. **Pflichten:** Eintrag in der Upstream-Abweichungsliste (18 DEV-1) · absichernder Unit-Test „Default ist `False`" · Re-Check bei jeder selektiven Upstream-Übernahme (AV-32).

## Geprüfte Alternativen

- **„Nur Konfiguration"** (Default im Code belassen, ausschließlich per Preset/Env deaktivieren) — **verworfen, weil fail-open:** Jede Config-Neuerzeugung (`jarvis init`, neuer Rechner, vergessene Sektion) reaktiviert die Telemetrie stillschweigend; die Upstream-Vorlage enthält die Sektion nicht.
- **„Analytics vollständig entfernen"** (Paket + posthog-Abhängigkeit ausbauen) — **verworfen, weil unnötige Core-Abweichung:** Das Redaction-/Allowlist-Engineering selbst ist laut Audit solide; das Problem sind allein die Defaults. Ein Ausbau wäre ein echter Core-Umbau (Server-, Frontend-, EventBus-Verdrahtung) mit dauerhafter Rebase-Last.

## Konsequenzen

Eine bewusst gepflegte Ein-Zeilen-Diff gegenüber Upstream (in 18 geführt, testgesichert, je Pick erneut geprüft). Ohne ausdrückliche Entscheidung des Eigentümers verlässt keine Nutzungstelemetrie das Gerät. **Status:** beschlossen; Umsetzung folgt mit der ersten Code-Phase (noch nicht umgesetzt).

## Verweise

Primärdokumente: 18 DEV-1, 02 §2.3. Regeln: AV-25, AV-32. Entscheidungen: DEC-006, DEC-027.

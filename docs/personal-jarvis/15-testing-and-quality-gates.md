---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-26, AV-27 (Test-Anteil), AV-28, AV-29
Zugehörige ADRs: ADR-0012
Verwandte DEC-Einträge: DEC-009, DEC-018
---

# 15 — Test- und Qualitätsarchitektur

## §1 Testtaxonomie

1. **Unit-Tests** — reine Logik (RiskEngine-Regeln, Merge-Planung, Normalisierung, Alias-Auflösung) und Repositories gegen Wegwerf-Datenbanken.
2. **Contract-Tests (zentral):** *eine* gemeinsame Suite je Vertrag — jeder Provideradapter (inkl. Fake) muss sie bestehen; ebenso der CredentialStore (InMemory + macOS-Keychain) und die PJR-Ports/OJRA (fixiert die Fassaden-Semantik gegen Upstream-Wechsel, AV-27).
3. **Integrationstests** — ActionPipeline Ende-zu-Ende (Vorschlag → Audit) gegen Fake-Adapter und echte DB; Outbox-Wiederanlauf nach simuliertem Absturz; Konflikt-, Tombstone- und Dubletten-Szenarien; identisches Verhalten der Transporte (API vs. CLI, AV-35).
4. **Migrationstests** — Vorwärtsmigration von jeder je veröffentlichten `schema_version` mit befüllten Beispieldaten; Ledger-/Prüfsummen-Verifikation; Backup-Restore-Roundtrip.
5. **Security-Tests** — Secret-Leak-Scan über Logs/Fehler/Exports; Berechtigungsmatrix (Workspace × Capability); Nachweis, dass R2 ohne Approval-Datensatz nicht ausführbar ist; SSRF-Fälle; „LLM-Ausgabe kann keinen Endpunkt setzen"; Egress: S2-/Unklassifiziert-Blockade, Herabstufungs-Verbot, Redaction-Derivate, Provider-Eigenschafts-Abgleich.
6. **Zustandsmaschinen-Tests** — Mail (`uncertain_outcome` ohne Auto-Neuversand), Verifikationszustände, Approval-Lifecycle, Merge-Zustandsfolge.
7. **Native macOS-Tests** — Keychain-Integration (Speichern/Rotieren/verweigert/gesperrt), TCC verweigert/entzogen (Native Bridge); laufen auf einem macOS-Runner (additiver CI-Workflow — schließt die im Audit belegte macOS-Lücke für den Personal-Teil).
8. **UI-End-to-End** — Kernflüsse gegen laufenden `serve` mit Fake-Adaptern (Konto anlegen, Entität erstellen/bestätigen, Konflikt auflösen, Freigabe erteilen); Werkzeug: DEC-D04.
9. **Kill-Switch-/Sperren-Tests** — R2-Stopp lässt Sync/R1 unberührt; `serve.lock` (zweiter Prozess, stale lock).
10. **Restore-Drill** — dokumentierter Wiederherstellungstest auf leerer Installation inkl. Mac-+Keychain-Verlust (13 §7).
11. **Live-Abnahme je Provideradapter** — dokumentierte Checkliste gegen einen echten Provider-Account (Anbieter: DEC-D11); Pflicht vor „fertig" (AV-26).
12. **Desktop-Regression** — Tauri-Smoke je Release: Start, Backend hoch, `/health`, Modulseiten rendern.

## §2 Quality-Gates

Pflicht vor Modul-Abschluss (mit 19 verzahnt): alle für das Modul einschlägigen Suiten aus §1 grün; Contract-Suiten für jeden neuen Adapter/Port; Migrationstests bei jedem Schemaeintrag; Security-Tests bei jeder neuen Capability-Operation. Die Test-Infrastruktur selbst folgt der Materialisierungsregel (AV-33): Gates entstehen mit dem ersten Modul, das sie braucht — bis dahin gilt manuelle Review gegen die Traceability-Matrix.

## §3 Prüfmechanik für Architekturtreue

1. **Traceability-Matrix als Prüfgrundlage:** je AV-Regel Primärdokument, Testtyp, Durchsetzungsstelle (traceability-matrix.md); Module aktualisieren berührte Zeilen (19).
2. **Strukturelle Checks (mit dem jeweils ersten Fachmodul materialisiert):** Import-Grenzen-Prüfung (Fachmodule ohne Upstream-Interna und ohne fremde Implementierungen, AV-6), CI-Contract-Suiten, Ledger-Tests, Egress-Guard-Tests.
3. **Prozess-Gates:** PR-Checkliste aus 19 und 01 §3 (geschützte Bereiche ⇒ ADR-Pflicht); Änderungen an geschützten Bereichen ohne referenzierten ADR gelten als abzulehnen.
4. Bis zur Tooling-Materialisierung: manuelle Review gegen die Matrix.

## §4 Testdaten und Doubles

Test-Doubles (Fakes, InMemory-Stores) sind ausschließlich in Tests zulässig (AV-3); produktive Pfade enthalten keine Mocks, Platzhalter oder Fake-Daten.

## §5 CI-Einbindung

Personal-Tests laufen als **additive** Workflows/Jobs (inkl. macOS-Runner für §1 Nr. 7); bestehende Upstream-Workflows bleiben unverändert (AV-1). Details entstehen mit dem ersten Modul (AV-33).

## §6 Unterstützte Toolchain (AV-29)

Verbindlich: **uv · Python exakt 3.12 · Rust stable ≥ 1.88 · maturin · Node.js 22+ für Frontend/Vite/Tauri · macOS Apple Silicon primär · Linux sekundär** (Kern- und spätere Serverplattform). Die Node-Zusatz-Bridges (WhatsApp-Baileys, Claude-Code-Runner) sind **nicht unterstützt** und werden nicht verwendet. Es werden keine ungetesteten Python-Versionen oder Plattformen als unterstützt behauptet. „Kein Node" gilt ausschließlich für die defekten Zusatz-Bridges, nicht für Frontend und Tauri (DEC-009).

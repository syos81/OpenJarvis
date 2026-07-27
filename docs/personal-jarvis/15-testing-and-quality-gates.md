---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-26, AV-27 (Test-Anteil), AV-28, AV-29
Zugehörige ADRs: ADR-0012, ADR-0018
Verwandte DEC-Einträge: DEC-009, DEC-018, DEC-034, DEC-038, DEC-042
---

# 15 — Test- und Qualitätsarchitektur

## §1 Testtaxonomie

1. **Unit-Tests** — reine Logik (RiskEngine-Regeln, Merge-Planung, Normalisierung, Alias-Auflösung) und Repositories gegen Wegwerf-Datenbanken.
2. **Contract-Tests (zentral):** *eine* gemeinsame Suite je Vertrag — jeder Provideradapter (inkl. Fake) muss sie bestehen; ebenso der CredentialStore (InMemory + macOS-Keychain) und die PJR-Ports/OJRA (fixiert die Fassaden-Semantik gegen Upstream-Wechsel, AV-27).
3. **Integrationstests** — ActionPipeline Ende-zu-Ende (Vorschlag → Audit) gegen Fake-Adapter und echte DB; Outbox-Wiederanlauf nach simuliertem Absturz; Konflikt-, Tombstone- und Dubletten-Szenarien; identisches Verhalten der Transporte (API vs. CLI, AV-35).
4. **Migrationstests** — Vorwärtsmigration von jeder je veröffentlichten `schema_version` mit befüllten Beispieldaten; Ledger-/Prüfsummen-Verifikation; Backup-Restore-Roundtrip.
5. **Security-Tests** — Secret-Leak-Scan über Logs/Fehler/Exports; Berechtigungsmatrix (Workspace × Capability); Nachweis, dass R2 ohne Approval-Datensatz nicht ausführbar ist; SSRF-Fälle; „LLM-Ausgabe kann keinen Endpunkt setzen"; Egress: S2-/Unklassifiziert-Blockade, Herabstufungs-Verbot, Redaction-Derivate, Provider-Eigenschafts-Abgleich.
6. **Zustandsmaschinen-Tests** — Mail (`uncertain_outcome` ohne Auto-Neuversand), Verifikationszustände, Approval-Lifecycle, Merge-Zustandsfolge.
7. **Native macOS-Tests** — Keychain-Integration (Speichern/Rotieren/verweigert/gesperrt), TCC verweigert/entzogen (Native Bridge); laufen auf macOS-Runnern **beider Zielarchitekturen** (arm64 und x86_64; additiver CI-Workflow — schließt die im Audit belegte macOS-Lücke für den Personal-Teil). Ergänzend weist CI je macOS-Release-Artefakt nach, dass der native Code **beider** Architekturen bereitgestellt wird — als Slices innerhalb eines Artefakts oder als je ein architekturspezifisches Artefakt (formatunabhängig, DEC-D17); fehlender nativer Code für eine Architektur ist ein Build-Fehler (§7, ADR-0018).
8. **UI-End-to-End** — Kernflüsse gegen laufenden `serve` mit Fake-Adaptern (Konto anlegen, Entität erstellen/bestätigen, Konflikt auflösen, Freigabe erteilen); Werkzeug: DEC-D04.
9. **Kill-Switch-/Sperren-Tests** — R2-Stopp lässt Sync/R1 unberührt; `serve.lock` (zweiter Prozess, stale lock).
10. **Restore-Drill** — dokumentierter Wiederherstellungstest auf leerer Installation inkl. Mac-+Keychain-Verlust (13 §7); **je Zielarchitektur** durchzuführen.
11. **Live-Abnahme je Provideradapter** — dokumentierte Checkliste gegen einen echten Provider-Account (Anbieter: DEC-D11); Pflicht vor „fertig" (AV-26); **je Zielarchitektur auf echter Hardware** zu erbringen (§7, ADR-0018).
12. **Desktop-Regression** — Tauri-Smoke je Release: Start, Backend hoch, `/health`, Modulseiten rendern; **je Zielarchitektur** (arm64 und x86_64).

## §2 Quality-Gates

Pflicht vor Modul-Abschluss (mit 19 verzahnt): alle für das Modul einschlägigen Suiten aus §1 grün; Contract-Suiten für jeden neuen Adapter/Port; Migrationstests bei jedem Schemaeintrag; Security-Tests bei jeder neuen Capability-Operation; **auf macOS zusätzlich die vollständig bestandene Dual-Architektur-Abnahmematrix (§7)**. Die Test-Infrastruktur selbst folgt der Materialisierungsregel (AV-33): Gates entstehen mit dem ersten Modul, das sie braucht — bis dahin gilt manuelle Review gegen die Traceability-Matrix.

## §3 Prüfmechanik für Architekturtreue

1. **Traceability-Matrix als Prüfgrundlage:** je AV-Regel Primärdokument, Testtyp, Durchsetzungsstelle (traceability-matrix.md); Module aktualisieren berührte Zeilen (19).
2. **Strukturelle Checks (mit dem jeweils ersten Fachmodul materialisiert):** Import-Grenzen-Prüfung (Fachmodule ohne Upstream-Interna und ohne fremde Implementierungen, AV-6), CI-Contract-Suiten, Ledger-Tests, Egress-Guard-Tests.
3. **Prozess-Gates:** PR-Checkliste aus 19 und 01 §3 (geschützte Bereiche ⇒ ADR-Pflicht); Änderungen an geschützten Bereichen ohne referenzierten ADR gelten als abzulehnen.
4. Bis zur Tooling-Materialisierung: manuelle Review gegen die Matrix.

## §4 Testdaten und Doubles

Test-Doubles (Fakes, InMemory-Stores) sind ausschließlich in Tests zulässig (AV-3); produktive Pfade enthalten keine Mocks, Platzhalter oder Fake-Daten.

## §5 CI-Einbindung

Personal-Tests laufen als **additive** Workflows/Jobs (inkl. macOS-Runner **beider Zielarchitekturen** für §1 Nr. 7 sowie der Slice-Prüfung je macOS-Artefakt); bestehende Upstream-Workflows bleiben unverändert (AV-1). Details entstehen mit dem ersten Modul (AV-33).

## §6 Unterstützte Toolchain (AV-29)

Verbindlich: **uv · Python exakt 3.12 · Rust stable ≥ 1.88 · maturin · Node.js 22+ für Frontend/Vite/Tauri**.

**Zielplattform macOS:** **Apple Silicon arm64 und Intel x86_64 sind gleichwertige produktive Zielarchitekturen; verbindliche Mindestversion ist macOS 12.3 auf beiden** (Untergrenze belegt durch die Contacts-API: `CNSaveRequest.transactionAuthor` ab macOS 12, `CNSaveRequest.shouldRefetchContacts` ab macOS 12.3). Beide Architekturen erhalten denselben fachlichen Funktionsumfang. **Für Apple Silicon arm64 und Intel x86_64 muss jeweils nativer ausführbarer Code gebaut und nachgewiesen werden. Laufzeit-, Sicherheits-, TCC- und Live-Abnahmen erfolgen separat auf echter Hardware der jeweiligen Architektur. Signierung, Packaging und Update-Auslieferung müssen sicherstellen, dass für beide Architekturen der korrekte native Code bereitgestellt und überprüft wird. Ob dies durch ein gemeinsames Universal-2-Artefakt oder durch zwei getrennte architekturspezifische Pakete erfolgt, bleibt bis zur Entscheidung DEC-D17 offen** (§7, ADR-0018, DEC-042). **Linux bleibt sekundäres späteres Ziel** (Kern- und spätere Serverplattform) ohne Abnahmepflicht in dieser Baseline.

**Python 3.12 ist produktive Pflicht** für Builds, Tests und den Kontakte-MASTER. Eine ältere Python-Version, die für isolierte kontaktfreie Spike-Skripte ausgereicht hat, ist **keine** produktive Toolchain-Abnahme.

Die Node-Zusatz-Bridges (WhatsApp-Baileys, Claude-Code-Runner) sind **nicht unterstützt** und werden nicht verwendet. Es werden keine ungetesteten Python-Versionen, Architekturen oder Plattformen als unterstützt behauptet. „Kein Node" gilt ausschließlich für die defekten Zusatz-Bridges, nicht für Frontend und Tauri (DEC-009, ergänzt durch DEC-042).

## §7 Dual-Architektur-Abnahmematrix (macOS)

Verbindliche Struktur der macOS-Abnahme je Modul (ADR-0018, DEC-042). Die Matrix trägt **zwei Pflichtspalten** — Apple Silicon arm64 und Intel x86_64. **Ein Gesamt-PASS existiert ausschließlich, wenn beide Spalten vollständig bestanden sind; ein Ergebnis der einen Architektur gilt niemals automatisch für die andere.**

Pflichtzeilen (soweit für das Modul einschlägig): nativer Build der Zielarchitektur · P0-Reachability der Native Bridge · Protokoll-/Contract-Suite · Ad-hoc-signiertes Artefakt · zertifikatssigniertes Artefakt · TCC-Erteilung und -Persistenz über Rebuild, Versions-Bump, Verschieben und Quarantäne · CRUD · Feldabdeckung · Delta-/Change-History-Pfad · Voll-Diff-Fallback · vereinheitlichte Datensätze · Desktop-Entwicklungsbetrieb · Betrieb aus der gepackten App · App-Neustart · Backup-/Restore-Roundtrip · vollständige Live-Abnahme gegen einen echten Provider-Account.

Regeln:

1. **Echte Hardware.** Geräteabhängige Zeilen (TCC, Codesigning, Bereitstellung des nativen Codes, Store-Zugriffe, gepackte App, Backup/Restore, Live-Abnahme) sind auf physischer Hardware der jeweiligen Architektur zu erbringen.
2. **Kein Rosetta-Ersatz.** Rosetta 2 übersetzt ausschließlich x86_64 → arm64; der umgekehrte Weg existiert nicht. Ein unter Rosetta auf Apple Silicon ausgeführter x86_64-Build ersetzt daher **keine** Prüfung auf echter Intel-Hardware, und die arm64-Abnahme ist auf Intel-Hardware technisch unmöglich. Rosetta darf in keiner Zeile als bestandener Nachweis geführt werden.
3. **Evidenzangabe.** Jede Zeile trägt Architektur, macOS-Version, Swift-/SDK-Version, Zertifikatsbezeichnung, Testbenutzer und Datum. Ein Toolchain-Wechsel entwertet die betroffenen Zeilen.
4. **Spike-Evidenz ist keine Abnahme.** Ergebnisse technischer Spikes gelten als Vor- bzw. Teilnachweis und ersetzen keine Zeile der Modulabnahme (AV-3, 19).
5. **Formatunabhängigkeit.** Die Matrix schreibt **kein** Auslieferungsformat vor. Sie verlangt ausschließlich, dass für jede Architektur der korrekte native Code bereitgestellt, überprüft und auf echter Hardware abgenommen wird — gleich ob er aus einem gemeinsamen Universal-2-Artefakt oder aus einem architekturspezifischen Paket stammt. Die Formatwahl ist als **DEC-D17** offen (17 §2); kein Prüfschritt darf eine der beiden Varianten voraussetzen.

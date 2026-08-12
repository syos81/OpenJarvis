---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-26, AV-27 (Test-Anteil), AV-28, AV-29
Zugehörige ADRs: ADR-0012, ADR-0018
Verwandte DEC-Einträge: DEC-009, DEC-018, DEC-034, DEC-038, DEC-042, DEC-043
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

> **Allgemeiner Prüfumfang: normativ ausschliesslich in
> [`docs/governance/openjarvis-dauerregeln.md`](../governance/openjarvis-dauerregeln.md)
> §12 (Testregel), §13 (Live-Abnahme), §14 (Plattformen) und §15 (minimaler
> Blockabschluss).** Dieses Dokument normiert den allgemeinen Prüfumfang nicht
> zweitens. Es führt die konkreten Testarten, modulbezogenen Prüfpunkte und
> die technischen Anforderungen; deren Auslösung richtet sich nach den
> Dauerregeln.

Vor Modul-Abschluss (mit 19 verzahnt): alle für das Modul einschlägigen Suiten aus §1 grün; Contract-Suiten für jeden neuen Adapter/Port; Migrationstests bei jedem Schemaeintrag; Security-Tests bei jeder neuen Capability-Operation. Der Umfang folgt dem Risikoprinzip der Dauerregeln §1 und §12 — es gibt keine Volltestpflicht bei jeder Änderung, keinen obligatorischen `module-final`-Schritt und keinen obligatorischen Fünf-Phasen-Lauf. Ob zusätzlich eine native Plattformabnahme nach §7 verlangt wird, entscheidet die Auslöseregel der Dauerregeln §14. Die Test-Infrastruktur selbst folgt der Materialisierungsregel (AV-33): Gates entstehen mit dem ersten Modul, das sie braucht — bis dahin gilt manuelle Review gegen die Traceability-Matrix.

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

**Befund 2026-07-28 (offener Defekt, dokumentiert, nicht korrigiert):** Die Packaging-Konfiguration `frontend/src-tauri/tauri.conf.json` führt unter `bundle.macOS` weiterhin `"minimumSystemVersion": "10.15"` und widerspricht damit der verbindlichen Untergrenze **12.3**. ADR-0018 §2 bezeichnet eine niedrigere Angabe ausdrücklich als Defekt, der **vor produktivem Desktop-Betrieb** zu korrigieren ist. Die Korrektur ist eine Produktcode-Änderung und erfolgt in der produktiven Implementierungsphase, nicht in dieser Dokumentationsaktualisierung. Bis dahin gilt: **kein produktives Desktop-Release**.

Die Node-Zusatz-Bridges (WhatsApp-Baileys, Claude-Code-Runner) sind **nicht unterstützt** und werden nicht verwendet. Es werden keine ungetesteten Python-Versionen, Architekturen oder Plattformen als unterstützt behauptet. „Kein Node" gilt ausschließlich für die defekten Zusatz-Bridges, nicht für Frontend und Tauri (DEC-009, ergänzt durch DEC-042).

## §7 Dual-Architektur-Abnahmematrix (macOS)

Struktur und Format der macOS-Abnahme je Modul (ADR-0018, DEC-042). Die Matrix trägt zwei Spalten — Apple Silicon arm64 und Intel x86_64. **Ein Ergebnis der einen Architektur gilt niemals automatisch für die andere.**

**Wann eine Spalte überhaupt zu erbringen ist, regeln die Dauerregeln §14**
([`docs/governance/openjarvis-dauerregeln.md`](../governance/openjarvis-dauerregeln.md)):
nur bei geändertem plattformspezifischem Pfad, bei nicht mehr übertragbarer
früherer Abnahme oder bei anstehendem Release-Smoke. Ein unveränderter, bereits
akzeptierter nativer Pfad wird nicht nach jedem anderen Block erneut geprüft;
Release-Smokes dürfen gebündelt werden. Die frühere pauschale Regel „Gesamt-PASS
nur bei zwei vollständig bestandenen Spalten nach jeder Änderung" ist damit als
allgemeine Prozessnorm abgelöst.

Pflichtzeilen (soweit für das Modul einschlägig): nativer Build der Zielarchitektur · P0-Reachability der Native Bridge · Protokoll-/Contract-Suite · Ad-hoc-signiertes Artefakt · zertifikatssigniertes Artefakt · TCC-Erteilung und -Persistenz über Rebuild, Versions-Bump, Verschieben und Quarantäne · CRUD · Feldabdeckung · Delta-/Change-History-Pfad · Voll-Diff-Fallback · vereinheitlichte Datensätze · Desktop-Entwicklungsbetrieb · Betrieb aus der gepackten App · App-Neustart · Backup-/Restore-Roundtrip · vollständige Live-Abnahme gegen einen echten Provider-Account.

Regeln:

1. **Echte Hardware.** Geräteabhängige Zeilen (TCC, Codesigning, Bereitstellung des nativen Codes, Store-Zugriffe, gepackte App, Backup/Restore, Live-Abnahme) sind auf physischer Hardware der jeweiligen Architektur zu erbringen.
2. **Kein Rosetta-Ersatz.** Rosetta 2 übersetzt ausschließlich x86_64 → arm64; der umgekehrte Weg existiert nicht. Ein unter Rosetta auf Apple Silicon ausgeführter x86_64-Build ersetzt daher **keine** Prüfung auf echter Intel-Hardware, und die arm64-Abnahme ist auf Intel-Hardware technisch unmöglich. Rosetta darf in keiner Zeile als bestandener Nachweis geführt werden.
3. **Evidenzangabe.** Jede Zeile trägt Architektur, macOS-Version, Swift-/SDK-Version, Zertifikatsbezeichnung, den gebundenen Abnahmescope und Datum. Ein Toolchain-Wechsel entwertet die betroffenen Zeilen. Ein **separater** Testbenutzer ist keine allgemeine Pflicht; verbindlich ist die Isolation des Abnahmescopes nach den Dauerregeln §3 — nur ausdrücklich zugelassene Ziele werden mutiert, bestehende private Daten sind kein Testziel. Wo ein separater Benutzer diese Isolation herstellt, wird er benannt.
4. **Spike-Evidenz ist keine Abnahme.** Ergebnisse technischer Spikes gelten als Vor- bzw. Teilnachweis und ersetzen keine Zeile der Modulabnahme (AV-3, 19).
5. **Formatunabhängigkeit.** Die Matrix schreibt **kein** Auslieferungsformat vor. Sie verlangt ausschließlich, dass für jede Architektur der korrekte native Code bereitgestellt, überprüft und auf echter Hardware abgenommen wird — gleich ob er aus einem gemeinsamen Universal-2-Artefakt oder aus einem architekturspezifischen Paket stammt. Die Formatwahl ist als **DEC-D17** offen (17 §2); kein Prüfschritt darf eine der beiden Varianten voraussetzen.

## §8 Abnahmestand Kontakte-Modul (Stand 2026-07-28)

Ausgefüllte Matrix nach der Struktur aus §7. **Zustände sind ausschließlich:** `PASS` · `FAIL` · `OPEN` · `NOT EXECUTABLE IN CURRENT ENVIRONMENT`. Mischbegriffe sind unzulässig; „teilweise", „weitgehend" oder „im Wesentlichen" gelten als `OPEN`.

**Grundlage:** Spike G3a (ADR-0016 Punkt 8, DEC-043). **Alle unten mit `PASS` geführten Zeilen sind Spike-Nachweise und damit nach §7 Nr. 4 technische Vor- bzw. Teilnachweise — sie ersetzen keine Modulabnahme** (AV-3, 19). Die Modulabnahme entsteht erst mit der produktiven Implementierung.

| Zeile | Apple Silicon arm64 | Intel x86_64 |
|---|---|---|
| Nativer Build der Zielarchitektur (`minos 12.3`) | PASS | PASS |
| P0-Reachability der Native Bridge (ObjC-Shim, `CNChangeHistory`) | PASS | PASS |
| Protokoll-/Contract-Suite (JSON-Lines, Handshake, `ping`, `caps`, Shutdown) | PASS | PASS |
| Ad-hoc-signiertes Artefakt (T3) | PASS | PASS |
| Zertifikatssigniertes Artefakt (T4, Hardened Runtime, DR zertifikatsbasiert) | PASS | PASS |
| TCC-Erteilung (Autorisierung erteilt, auf den Sidecar attribuiert) | PASS | PASS |
| Vollständige TCC-Persistenzmatrix (Rebuild, Versions-Bump, Verschieben, Quarantäne) | OPEN | OPEN |
| Containerzugriff | PASS | OPEN |
| Enumerate (vollständiger Lesepfad, aktueller Diagnosestand) | PASS | OPEN |
| CRUD | PASS | OPEN |
| Feldabdeckung | PASS | OPEN |
| Delta-/Change-History-Pfad (inkl. externer Änderung, Echo-Unterdrückung, ungültiges Token) | PASS | OPEN |
| Voll-Diff-Fallback | PASS | OPEN |
| Isolation und laufgebundene Bereinigung (Fremdkontakte/Me-Karte unangetastet) | PASS | OPEN |
| Vereinheitlichte Datensätze (Mehrcontainer/Unified) | NOT EXECUTABLE IN CURRENT ENVIRONMENT | OPEN |
| Betrieb aus der gepackten App — **kontaktfreier** Handshake | OPEN | PASS |
| Betrieb aus der gepackten App — **echte Kontakteoperation** | OPEN | OPEN |
| Desktop-Entwicklungsbetrieb | OPEN | OPEN |
| App-Neustart | OPEN | OPEN |
| Backup-/Restore-Roundtrip | OPEN | OPEN |
| Vollständige Live-Abnahme gegen einen echten Provider-Account | OPEN | OPEN |

**Zur Zeile „vereinheitlichte Datensätze" auf arm64:** Der Mehrcontainer-Test verlangt mindestens zwei Container; der Abnahme-Testbenutzer hat genau einen (belegt) und bewusst weder Apple-ID noch iCloud. `NOT EXECUTABLE IN CURRENT ENVIRONMENT` bedeutet **weder bestanden noch fehlgeschlagen**: geprüft wurde nichts. Die Zeile ist auf einer Installation mit zwei Containern nachzuholen und zählt bis dahin wie `OPEN` gegen den Modulabschluss.

**Ergänzender Nachweisstand:** 187 kontaktfreie Prüfungen (Protokoll, Treiber-Fehlermodi, Autorisierungsprofile, Enumerate-Diagnose, Isolation, Ergebnisberichterstattung) sind grün. Sie sind architekturneutral und ersetzen **keine** geräteabhängige Zeile dieser Matrix.

**Gesamtstatus:**

1. **Die produktive Implementierung des Kontakte-Moduls darf beginnen** (16 §4, ADR-0016 Punkt 8).
2. **Der Modulabschluss des Kontaktmoduls bleibt gesperrt.** Beide Spalten enthalten `OPEN`-Zeilen (19 §10). Das ist eine modulbezogene Statusaussage; welche Zeilen erneut zu erbringen sind, richtet sich nach den Dauerregeln §14.
3. Kein `OPEN` und kein `NOT EXECUTABLE IN CURRENT ENVIRONMENT` darf ohne die zugehörige Live-Abnahme auf echter Hardware nach `PASS` gesetzt werden (§7 Nr. 1–3).

### §8.1 Produktive Abnahme Kontakte (Stand 2026-08-04)

§8 ist die **Spike**-Matrix und bleibt unverändert stehen. Diese Tabelle führt
den Stand der **produktiven** Implementierung; sie ersetzt §8 nicht, sondern
tritt daneben. Zustände unverändert: `PASS` · `FAIL` · `OPEN` ·
`NOT EXECUTABLE IN CURRENT ENVIRONMENT`.

Evidenz Intel-Spalte durchgehend: x86_64, macOS 12.7.6 (21H1320), Swift 5.7.2 /
SDK 13.1, Zertifikat „Personal Jarvis Contacts Spike", Hauptbenutzer mit
Ablageort „Auf meinem Mac", 2026-08-01 bis 2026-08-04.

Evidenz arm64-Spalte durchgehend: Mac14,12 (Mac mini M2 Pro), arm64 nativ
(`sysctl.proc_translated = 0`), macOS 26.2 (25C56), Swift 6.3.2 / SDK 26.5,
Zertifikat „de.kluender.jarvis" (Blatt `b1038059…`), Zielcontainer
`_local:ABAccount`, 2026-08-12.

| Zeile | Apple Silicon arm64 | Intel x86_64 |
|---|---|---|
| Nativer Build und zertifikatsgebundene Signierung (App, Sidecar, Write-Helper) | PASS | PASS ohne Write-Helper (Nachtrag unten) |
| Write-Helper im Bundle, kontaktfreie Bundle-Suite | PASS | UNPROVEN (Nachtrag unten) |
| Lesen, Containerinventar, Enumerate aus der gepackten App | PASS | PASS |
| Delta-/Change-History-Pfad | PASS | PASS |
| Voll-Diff-Fallback | OPEN | PASS |
| Create live (ein Claim, ein Save, Read-back-Digest identisch) | PASS | PASS |
| Update live (Patch-Semantik, Listenposition, Identität unverändert) | PASS | PASS |
| Delete live (R2, `confirm_delete`, Abwesenheitsnachweis, Tombstone) | PASS | PASS |
| At-most-once unter Absturz (`outcome_unknown`, kein zweiter Send) | OPEN | PASS |
| Lifecycle und Shutdown inkl. Eltern-Watchdog nach GUI-Absturz | PASS | PASS |
| App-Neustart mit `recover_interrupted()` | OPEN | PASS |
| Vollständige TCC-Persistenzmatrix (Rebuild, Versions-Bump, Verschieben, Quarantäne) | OPEN | **OPEN** |
| Vereinheitlichte Datensätze (Mehrcontainer/Unified) | NOT EXECUTABLE IN CURRENT ENVIRONMENT | **OPEN** |
| Backup-/Restore-Roundtrip über den Backup-Kern | OPEN | **OPEN** |
| Apple-Kontakte-Pixelabgleich auf demselben Gerät | OPEN | OPEN |

**Was hinter den arm64-`OPEN`-Zeilen konkret fehlt:**

*Voll-Diff-Fallback.* Zwei Delta-Läufe über beide Container liefen
erfolgreich; ein Voll-Diff wurde nie gefordert (`requires_full_diff =
false`) und deshalb auch nicht ausgelöst. Der Pfad ist unbelegt.

*At-most-once unter Absturz.* Der Eltern-Watchdog ist belegt: SIGKILL auf
die GUI beendete das Backend in 4 s, ohne Restprozess. Ein Absturz
**während** eines laufenden `CNSaveRequest` wurde nicht herbeigeführt;
`executing → outcome_unknown` bleibt auf arm64 unbelegt.

*App-Neustart mit `recover_interrupted()`.* Zwei Neustarts verliefen sauber,
alle drei Vorgänge blieben danach `succeeded` mit je einem Versuch. Es
existierte jedoch kein unterbrochener Vorgang — die Erholung lief leer und
zählt nach §9 nicht als Nachweis.

*Vereinheitlichte Datensätze.* Anders als beim Intel-Abnahmebenutzer hat
dieses Gerät **zwei** Container, und beide werden vollständig enumeriert
(114/114 und 1/1, `complete`, zählkonsistent). Der Vereinheitlichungsfall
selbst tritt trotzdem nicht ein: kein Datensatz trägt einen
`unified_identifier`, kein Kontakt existiert in beiden Containern. Ihn
herbeizuführen hiesse, einen Testdatensatz in den cardDAV-Container zu
schreiben und damit nach aussen zu replizieren — eine Eigentümerentscheidung,
keine Bauarbeit. Die Einstufung heisst wie in §8: weder bestanden noch
fehlgeschlagen.

*Pixelabgleich.* Alle acht Tokengruppen in
`frontend/src/personal/contacts/tokens.css` tragen weiterhin den Marker
`M2-VORLÄUFIG`; laut Dateikopf ist jeder markierte Wert eine begründete
Intel-Schätzung. Die Eigentümer-Sichtprüfung am 2026-08-12 auf diesem Gerät
ergab deutliche Abweichungen gegenüber der nativen App. Der Referenzvertrag
([contacts-frontend-apple-redesign-2026-08-02.md](contacts-frontend-apple-redesign-2026-08-02.md)
§1) verlangt dafür zehn definierte Referenzaufnahmen und die Reihenfolge
(a) Aufnahmen, (b) eine Runde ausschliesslich `tokens.css`, (c) gezielte
Komponentenkorrekturen, (d) Abgleich Szene für Szene. Die Aufnahmen
existieren nicht; ohne sie ist die Zeile nicht schliessbar.

**Zur Intel-Spalte:** Der Intel-**Zweig** ist abgeschlossen und eingefroren
(modules/contacts.md §15.2). Die drei fett markierten Zeilen sind davon
ausgenommen — sie sind keine Intel-Bauarbeit, sondern Abnahmezeilen des
Modulabschlusses, und sie bleiben offen. Ein „Intel fertig" im Sinne von
19 §10 existiert nicht, solange sie offen sind.

**Nachtrag 2026-08-12 zum Write-Helper (betrifft beide Spalten).** Auf arm64
wurde am gebauten Bundle mechanisch festgestellt: `tauri build` signiert den
Schreibhelfer mit den Entitlements der **App** — neun Einträge statt dem
einen, den ADR-0026 bindet — und gibt ihm den Identifier
`contacts-write-helper` statt `de.kluender.jarvis.contacts-write-helper`,
weil `scripts/reseal-contacts-sidecar.sh` ihn nicht erfasste. Zusätzlich war
der Bundle-Pfad in `tests/personal/contacts/test_write_helper_bundle.py`
fest auf `x86_64-apple-darwin` verdrahtet, wodurch die achtzehn Prüfungen
dieser Kette auf arm64 lautlos übersprangen. Beides ist korrigiert und auf
arm64 belegt.

Der Teilnachweis **write-helper packaging / signing / identifier /
entitlements** wird für x86_64 deshalb ab sofort als `UNPROVEN` geführt, bis
auf Intel ein gezielter Revalidierungsblock gelaufen ist. Ausdrücklich
**nicht** behauptet wird, dass das damalige konkrete Intel-Bundle denselben
Fehler trug — das ist auf Intel nicht geprüft, und ohne Prüfung gibt es dazu
keine Aussage (§6). Der übrige Intel-Abschluss bleibt unberührt.

**Zur arm64-Spalte:** Am 2026-08-12 auf dem Mac mini M2 Pro erstmals
bearbeitet. Keine Zeile ist aus der Intel-Spalte übernommen (§7 Nr. 1–2,
DEC-042); jede `PASS`-Zeile beruht auf einer Beobachtung auf diesem Gerät.
Die Reihenfolge der Abarbeitung steht als M2-Checkliste in
[contacts-native-update-delete-intel-2026-08-04.md](contacts-native-update-delete-intel-2026-08-04.md)
§17.

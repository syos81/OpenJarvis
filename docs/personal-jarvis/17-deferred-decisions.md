---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-30 (Entscheidungsweg), AV-33
Zugehörige ADRs: — (Entscheidungen erfolgen später je per ADR bzw. ausdrücklicher Freigabe)
Verwandte DEC-Einträge: DEC-D01 bis DEC-D16
---

# 17 — Deferred Decisions

## §1 Vorwegnahme-Verbot

Die folgenden 16 Entscheidungen sind **bewusst offen**. Kein Dokument, kein ADR und keine Implementierung darf sie vorwegnehmen. Jede wird **vor der ersten betroffenen Implementierung** ausdrücklich entschieden (Freigabe durch den Eigentümer; Ergebnis wandert ins Entscheidungsregister und ggf. in einen ADR). Empfehlungen sind unverbindlich und **eindeutig als „nicht beschlossen" gekennzeichnet**.

## §2 Liste

| ID | Entscheidung | Kontext / Optionen | Empfehlung (nicht beschlossen) | Auslöser |
|---|---|---|---|---|
| DEC-D01 | **Native-Bridge-Technik** | PyObjC in-process vs. schmaler Swift-Helper (JSON-stdio) für EventKit/CNContactStore (08 §4) | Start mit PyObjC; Swift-Helper als Fallback | Materialisierung des ersten Apple-nativen Adapters |
| DEC-D02 | **Keychain-Anbindung** | `keyring`-Bibliothek vs. eigene schmale Security-Framework-Integration (09 §4) | `keyring` hinter dem CredentialStore-Vertrag | Materialisierung des CredentialStore |
| DEC-D03 | **Recovery-Key-Format und optionale Passphrase** | Wortfolge/Schlüsseldatei; Passphrase-Hülle zusätzlich? (13 §2) | Recovery Key verpflichtend + Passphrase optional | Materialisierung des Backup-Kerns |
| DEC-D04 | **UI-E2E-Werkzeug** | Playwright vs. Component-Tests only (15 §1 Nr. 8) | Playwright (additiv) | erstes Modul mit UI-E2E-Pflicht |
| DEC-D05 | **Session-Token-TTL und Rotation** | Feinwerte für 09 §1 | TTL 8 h, Rotation 30 min vor Ablauf, Invalidierung bei App-Exit | Materialisierung der Auth |
| DEC-D06 | **Optionale native R2-Zweitbestätigung** | Tauri-Dialog als Dekoration des transportneutralen ApprovalClient (09 §2) | ja, als Feature-Schalter | erstes R2-Modul |
| DEC-D07 | **Audit-Checkpoint-Kadenz und externes Medium** | manueller Export: Rhythmus, Medium (13 §5) | monatlich + bei jedem R2-Modul-Go-Live | Materialisierung des Audit-Kerns |
| DEC-D08 | **Chat-Migration in die Personal-Datenhoheit (Zeitpunkt)** | Richtung ist entschieden (DEC-019, 06 §3); offen ist der Zeitpunkt | mit dem Fachmodul „Chat & Sessions" | Planung des Chat-Moduls |
| DEC-D09 | **Sensitivitätsmatrix einzelner Datentypen** | Zuordnung S1/S2 je Feld/Datentyp (12 §1) | Vorschlagsmatrix mit erstem LLM-nutzendem Modul | erstes LLM-nutzendes Modul |
| DEC-D10 | **Erstes Fachmodul und Modulreihenfolge** | 16 §4 nennt nur Startkriterien | — (bewusst keine) | gesonderte Freigabe nach Architektur-Materialisierung |
| DEC-D11 | **Live-Abnahme-Anbieter** | echter Provider-Account je Adapter (15 §1 Nr. 11) | — | je Modul vor der Abnahme |
| DEC-D12 | **Broker-Ziel** | realer Broker mit API zur Validierung des BrokerAdapter-Vertrags | — (providerneutral bleibt Pflicht) | weit vor dem Trading-Modul |
| DEC-D13 | **Home-Server-Secret-Store** | servergeeigneter Secret Store für späteren unbeaufsichtigten Betrieb (09 §4) | — (darf die macOS-Architektur nicht schwächen) | Planung eines Home-Server-Betriebs |
| DEC-D14 | **Mail-Skalenpolitik** | Sync-Fenster/Archivstrategie großer Postfächer (16 §2) | rollierendes Fenster + Archiv on demand | Planung des Mail-Moduls |
| DEC-D15 | **Initiale Workspaces** | Startbelegung (z. B. Privat, Arbeit, Hausverwaltung) — frei konfigurierbar (06 §6) | — (Nutzerwahl) | Inbetriebnahme des ersten Moduls |
| DEC-D16 | **Backup-Ziele und Aufbewahrung** | Zielorte, Rotation, Aufbewahrungsfristen (13 §3) | lokal + ein externes Ziel, täglich, 30/12-Rotation | Materialisierung des Backup-Kerns |

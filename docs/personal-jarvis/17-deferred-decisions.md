---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-30 (Entscheidungsweg), AV-33
Zugehörige ADRs: ADR-0016, ADR-0017 (Auflösung von DEC-D01/D02); weitere Entscheidungen erfolgen je per ADR bzw. ausdrücklicher Freigabe
Verwandte DEC-Einträge: DEC-D01 bis DEC-D16; DEC-030 bis DEC-040
---

# 17 — Deferred Decisions

## §1 Vorwegnahme-Verbot und aktueller Stand

Ursprünglich waren **16 Entscheidungen bewusst offen**. Kein Dokument, kein ADR und keine Implementierung darf eine noch offene Entscheidung vorwegnehmen. Jede wird **vor der ersten betroffenen Implementierung** ausdrücklich entschieden (Freigabe durch den Eigentümer; Ergebnis wandert ins Entscheidungsregister und ggf. in einen ADR). Empfehlungen sind unverbindlich und **eindeutig als „nicht beschlossen" gekennzeichnet**.

**Stand 2026-07-27** (Auslöser: Wahl des ersten Fachmoduls „Kontakte"):

- **Vollständig offen bleiben genau 5:** DEC-D06, DEC-D08, DEC-D12, DEC-D13, DEC-D14.
- **Teilentschieden: DEC-D09** — die Kontakt-Modul-Klassifizierung ist entschieden (DEC-037), die **globale Sensitivitätsmatrix bleibt offen**. DEC-D09 gilt weder als vollständig erledigt noch als vollständig offen.
- **Entschieden:** DEC-D01 (DEC-031), DEC-D02 (DEC-032), DEC-D03 (DEC-033), DEC-D04 (DEC-034), DEC-D05 (DEC-035), DEC-D07 (DEC-036), DEC-D15 (DEC-039), DEC-D16 (DEC-040).
- **Für Modul 1 aufgelöst, je künftigem Modul erneut zu entscheiden:** DEC-D10 (Modulwahl Kontakte = DEC-030; Gesamtreihenfolge weiterhin offen) und DEC-D11 (Abnahmeziel Modul 1 = DEC-038).

Maßgeblich für den Entscheidungstext ist stets das Entscheidungsregister; die Spalte „Empfehlung" unten bleibt historisch und ist für entschiedene Punkte gegenstandslos.

## §2 Liste

| ID | Entscheidung | Kontext / Optionen | Empfehlung (historisch, nicht beschlossen) | **Status / Auflösung bzw. Auslöser** |
|---|---|---|---|---|
| DEC-D01 | **Native-Bridge-Technik** | PyObjC in-process vs. schmaler Swift-Helper (JSON-stdio) für EventKit/CNContactStore (08 §4) | Start mit PyObjC; Swift-Helper als Fallback | **entschieden 2026-07-27 → DEC-031 (ADR-0016): Swift-Sidecar mit verpflichtendem Spike; bei Scheitern kein automatischer PyObjC-Wechsel** |
| DEC-D02 | **Keychain-Anbindung** | `keyring`-Bibliothek vs. eigene schmale Security-Framework-Integration (09 §4) | `keyring` hinter dem CredentialStore-Vertrag | **entschieden 2026-07-27 → DEC-032 (ADR-0017)** |
| DEC-D03 | **Recovery-Key-Format und optionale Passphrase** | Wortfolge/Schlüsseldatei; Passphrase-Hülle zusätzlich? (13 §2) | Recovery Key verpflichtend + Passphrase optional | **entschieden 2026-07-27 → DEC-033** |
| DEC-D04 | **UI-E2E-Werkzeug** | Playwright vs. Component-Tests only (15 §1 Nr. 8) | Playwright (additiv) | **entschieden 2026-07-27 → DEC-034** |
| DEC-D05 | **Session-Token-TTL und Rotation** | Feinwerte für 09 §1 | TTL 8 h, Rotation 30 min vor Ablauf, Invalidierung bei App-Exit | **entschieden 2026-07-27 → DEC-035** |
| DEC-D06 | **Optionale native R2-Zweitbestätigung** | Tauri-Dialog als Dekoration des transportneutralen ApprovalClient (09 §2) | ja, als Feature-Schalter | **offen** — erstes R2-Modul |
| DEC-D07 | **Audit-Checkpoint-Kadenz und externes Medium** | manueller Export: Rhythmus, Medium (13 §5) | monatlich + bei jedem R2-Modul-Go-Live | **entschieden 2026-07-27 → DEC-036** |
| DEC-D08 | **Chat-Migration in die Personal-Datenhoheit (Zeitpunkt)** | Richtung ist entschieden (DEC-019, 06 §3); offen ist der Zeitpunkt | mit dem Fachmodul „Chat & Sessions" | **offen** — Planung des Chat-Moduls |
| DEC-D09 | **Sensitivitätsmatrix einzelner Datentypen** | Zuordnung S1/S2 je Feld/Datentyp (12 §1) | Vorschlagsmatrix mit erstem LLM-nutzendem Modul | **teilentschieden:** Kontakt-Modul-Klassifizierung 2026-07-27 → DEC-037; **globale Matrix weiterhin offen** (erstes LLM-nutzendes Modul) |
| DEC-D10 | **Erstes Fachmodul und Modulreihenfolge** | 16 §4 nennt nur Startkriterien | — (bewusst keine) | **Modulwahl entschieden 2026-07-27 → DEC-030 (Kontakte); Gesamtreihenfolge weiterhin offen** |
| DEC-D11 | **Live-Abnahme-Anbieter** | echter Provider-Account je Adapter (15 §1 Nr. 11) | — | **für Modul 1 entschieden 2026-07-27 → DEC-038; je weiterem Modul erneut festzulegen** |
| DEC-D12 | **Broker-Ziel** | realer Broker mit API zur Validierung des BrokerAdapter-Vertrags | — (providerneutral bleibt Pflicht) | **offen** — weit vor dem Trading-Modul |
| DEC-D13 | **Home-Server-Secret-Store** | servergeeigneter Secret Store für späteren unbeaufsichtigten Betrieb (09 §4) | — (darf die macOS-Architektur nicht schwächen) | **offen** — Planung eines Home-Server-Betriebs |
| DEC-D14 | **Mail-Skalenpolitik** | Sync-Fenster/Archivstrategie großer Postfächer (16 §2) | rollierendes Fenster + Archiv on demand | **offen** — Planung des Mail-Moduls |
| DEC-D15 | **Initiale Workspaces** | Startbelegung (z. B. Privat, Arbeit, Hausverwaltung) — frei konfigurierbar (06 §6) | — (Nutzerwahl) | **entschieden 2026-07-27 → DEC-039** |
| DEC-D16 | **Backup-Ziele und Aufbewahrung** | Zielorte, Rotation, Aufbewahrungsfristen (13 §3) | lokal + ein externes Ziel, täglich, 30/12-Rotation | **entschieden 2026-07-27 → DEC-040** |

---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-30 (Entscheidungsweg), AV-33
Zugehörige ADRs: ADR-0016, ADR-0017 (Auflösung von DEC-D01/D02), ADR-0018 (Auslöser von DEC-D17); weitere Entscheidungen erfolgen je per ADR bzw. ausdrücklicher Freigabe
Verwandte DEC-Einträge: DEC-D01 bis DEC-D17; DEC-030 bis DEC-043
---

# 17 — Deferred Decisions

## §1 Vorwegnahme-Verbot und aktueller Stand

Ursprünglich waren **16 Entscheidungen bewusst offen**; mit DEC-D17 (2026-07-27) sind es **17**. Kein Dokument, kein ADR und keine Implementierung darf eine noch offene Entscheidung vorwegnehmen. Jede wird **vor der ersten betroffenen Implementierung** ausdrücklich entschieden (Freigabe durch den Eigentümer; Ergebnis wandert ins Entscheidungsregister und ggf. in einen ADR). Empfehlungen sind unverbindlich und **eindeutig als „nicht beschlossen" gekennzeichnet**.

**Stand 2026-07-31** (Auslöser: Übernahme des Reuse-Audits und Festlegung der Modulreihenfolge bis Modul 3):

- **Vollständig offen bleiben genau 5:** DEC-D06, DEC-D08, DEC-D13, DEC-D14, **DEC-D17**.
- **Teilentschieden (2):** **DEC-D09** — Kontakt-Modul-Klassifizierung entschieden (DEC-037), globale Sensitivitätsmatrix offen — und **DEC-D12** (neu) — Trading-Stufung T1–T4 und Abgrenzung entschieden (DEC-049, ADR-0024), Broker-Zielanbieter offen (Auslöser vor Moduleinstieg T4).
- **Entschieden:** DEC-D01 (DEC-031), DEC-D02 (DEC-032), DEC-D03 (DEC-033), DEC-D04 (DEC-034), DEC-D05 (DEC-035), DEC-D07 (DEC-036), **DEC-D10 (neu vollständig: DEC-030 + DEC-045/ADR-0019)**, DEC-D15 (DEC-039), DEC-D16 (DEC-040).
- **Für Modul 1 aufgelöst, je künftigem Modul erneut zu entscheiden:** DEC-D11 (Abnahmeziel Modul 1 = DEC-038).

**Frühere Stände:** Am 2026-07-27 waren 6 vollständig offen (inkl. DEC-D12) und DEC-D09 teilweise offen; DEC-D10 galt nur in der Modulwahl als entschieden, die Gesamtreihenfolge blieb offen. Mit DEC-045 (ADR-0019) ist die Reihenfolge bis Modul 3 festgelegt und DEC-D10 vollständig aufgelöst; mit DEC-049 (ADR-0024) ist DEC-D12 von vollständig offen auf teilweise offen gewechselt.

Maßgeblich für den Entscheidungstext ist stets das Entscheidungsregister; die Spalte „Empfehlung" unten bleibt historisch und ist für entschiedene Punkte gegenstandslos.

**Ergänzung 2026-07-27 (Auslieferungsformat):** ADR-0018 (DEC-042) entscheidet die Dual-Architektur-Unterstützung, lässt jedoch das **macOS-Auslieferungsformat** ausdrücklich offen. Diese Frage ist als **DEC-D17** regulär als offene Entscheidung registriert (§2, §3). Sie ist der erste Eintrag über die 16 ursprünglichen Deferred Decisions hinaus; die Liste umfasst damit **17 Einträge**. Seit der Aktualisierung 2026-07-31 (DEC-045, DEC-049) sind davon **5 vollständig offen: DEC-D06, DEC-D08, DEC-D13, DEC-D14, DEC-D17** (bei Registrierung von DEC-D17 am 2026-07-27 waren es 6, inkl. des inzwischen teilentschiedenen DEC-D12). Eine unverbindliche Empfehlung zugunsten von Universal 2 besteht, gilt aber **nicht** als beschlossen (Vorwegnahme-Verbot).

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
| DEC-D10 | **Erstes Fachmodul und Modulreihenfolge** | 16 §4 nennt nur Startkriterien | — (bewusst keine) | **vollständig entschieden: Modulwahl 2026-07-27 → DEC-030 (Kontakte); Reihenfolge bis Modul 3 2026-07-31 → DEC-045 (ADR-0019); nach Modul 3 bewusste Neuentscheidung** |
| DEC-D11 | **Live-Abnahme-Anbieter** | echter Provider-Account je Adapter (15 §1 Nr. 11) | — | **für Modul 1 entschieden 2026-07-27 → DEC-038; je weiterem Modul erneut festzulegen** |
| DEC-D12 | **Broker-Ziel** | realer Broker mit API zur Validierung des BrokerAdapter-Vertrags | — (providerneutral bleibt Pflicht) | **teilentschieden 2026-07-31:** Trading-Stufung T1–T4 und Abgrenzung → DEC-049 (ADR-0024); **Broker-Zielanbieter offen**, Auslöser präzisiert: vor Moduleinstieg T4 |
| DEC-D13 | **Home-Server-Secret-Store** | servergeeigneter Secret Store für späteren unbeaufsichtigten Betrieb (09 §4) | — (darf die macOS-Architektur nicht schwächen) | **offen** — Planung eines Home-Server-Betriebs |
| DEC-D14 | **Mail-Skalenpolitik** | Sync-Fenster/Archivstrategie großer Postfächer (16 §2) | rollierendes Fenster + Archiv on demand | **offen** — Planung des Mail-Moduls |
| DEC-D15 | **Initiale Workspaces** | Startbelegung (z. B. Privat, Arbeit, Hausverwaltung) — frei konfigurierbar (06 §6) | — (Nutzerwahl) | **entschieden 2026-07-27 → DEC-039** |
| DEC-D16 | **Backup-Ziele und Aufbewahrung** | Zielorte, Rotation, Aufbewahrungsfristen (13 §3) | lokal + ein externes Ziel, täglich, 30/12-Rotation | **entschieden 2026-07-27 → DEC-040** |
| DEC-D17 | **macOS-Auslieferungsformat** | ein signiertes Universal-2-Artefakt gegenüber zwei getrennten signierten Release-Artefakten für arm64 und x86_64 (§3; AV-29, 15 §6/§7) | Universal 2 — **unverbindlich, ausdrücklich nicht beschlossen** | **offen** — spätestens vor dem ersten produktiven Desktop-Release und vor endgültiger Festlegung von Updater-Manifest und Release-Artefakten (Auslöser: ADR-0018, DEC-042) |

## §3 DEC-D17 — macOS-Auslieferungsformat (offen)

**Entscheidungsfrage:** „Wird Personal Jarvis für macOS als ein signiertes Universal-2-Artefakt oder als zwei getrennte signierte Release-Artefakte für arm64 und x86_64 ausgeliefert?"

**Verbindliche Abgrenzung (gilt unabhängig vom Ausgang):**

1. DEC-D17 ändert **nichts** an der gleichwertigen Unterstützung beider Architekturen (DEC-042, AV-29).
2. DEC-D17 ändert **nichts** an der getrennten Live-Abnahme auf echter Hardware je Architektur (15 §7).
2a. **Der Kontakte-Bridge-Spike G3a nimmt DEC-D17 nicht vorweg** (Ergänzung 2026-07-28, DEC-043). Er hat je Architektur getrennt gebaut und signiert — das ist eine Arbeitsweise während der Entwicklung und **keine** Vorentscheidung über das Release-Format. Weder ein Universal-2-Artefakt noch zwei getrennte Pakete werden dadurch bevorzugt, vorgeschrieben oder ausgeschlossen. Die unverbindliche Empfehlung zugunsten von Universal 2 bleibt **ausdrücklich nicht beschlossen**. **DEC-D17 bleibt offen.**
3. **Beide Varianten müssen denselben fachlichen Funktionsumfang und dieselben Sicherheitsregeln liefern.** Ein Format, das eine Architektur funktional oder sicherheitsseitig schlechter stellt, ist unzulässig.
4. Eine Entscheidung darf **erst nach vorliegenden technischen Packaging-, Codesigning-, TCC-, Updater- und Rollback-Nachweisen** getroffen werden — nicht auf Basis von Präferenz oder Aufwandsschätzung allein.

**Entscheidungsauslöser:** spätestens vor dem ersten produktiven Desktop-Release; zusätzlich vor der endgültigen Festlegung des Updater-Manifests und der Release-Artefakte.

**Erforderliche Evidenz vor der Entscheidung:**

- reproduzierbarer Build je Variante;
- Nachweis beider nativer Slices bzw. beider architekturspezifischer Artefakte;
- Codesigning und Designated Requirements je Variante;
- TCC-Persistenz (Rebuild, Versions-Bump, Verschieben, Quarantäne);
- Updater-Kompatibilität (Manifest, Kanal, Plattformschlüssel);
- Rollback-Verhalten;
- Download- und Installationsgröße;
- CI-Aufwand;
- Fehlzuordnungsrisiko (falsches Artefakt auf falscher Architektur);
- Wartbarkeit.

Bis zur Entscheidung darf **kein** Dokument eine der beiden Varianten vorschreiben oder ausschließen (17 §1, Vorwegnahme-Verbot).

---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-8, AV-16, AV-18, AV-33
Zugehörige ADRs: ADR-0006 (Trading-Orders immer R2), ADR-0019, ADR-0021, ADR-0022
Verwandte DEC-Einträge: DEC-005, DEC-045, DEC-049; offen: DEC-D12 (Broker-Ziel, Auslöser präzisiert: vor Moduleinstieg T4)
---

# ADR-0024: Gestufte Trading-Architektur (T1–T4) und Modul 3 „Trading Intelligence"

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Trading ist ein verbindlicher Zielbereich, aber die Modulkarte führte „Trading" bisher als einen einzigen, pauschal R2-klassifizierten Block. Der Eigentümer hat eine gestufte Architektur festgelegt und **Trading Intelligence (T1)** als Modul 3 bestimmt (DEC-045). Die R2-Regeln aus 10 §1/§2 (Orders immer R2, keine LLM-Direktorders, AV-18) bleiben unverändert.

## Entscheidung

1. **Stufung (verbindlich):** **T1 Trading Intelligence** · **T2 Portfolio und Tradingjournal** · **T3 Strategy Lab** · **T4 Broker und Execution**. **Autonomes Live-Trading** ist keine Stufe dieses Plans und erfolgt ausschließlich nach einer späteren eigenen Architektur-, Sicherheits-, Risiko- und Haftungsentscheidung. Jede Stufe ist ein eigenes vertikales Modul nach ADR-0019; nur **T1 ist als Modul 3 eingeplant**; T2–T4 erhalten jetzt keine Position (Neuentscheidung nach Modul 3).
2. **T1-Scope (verbindlich):** Instrumentensuche mit stabilen IDs · kanonische Markt- und Nachrichtenquellen · aktuelle Kurse · historische Kursdaten · Watchlists · Charts und Vergleichsansichten · Unternehmens- und Marktnachrichten · Internetrecherche mit Quellen · Datenaktualität und Provenienz · regelbasierte Kurs-, Volumen- und Nachrichtenalarme · automatische tägliche und wöchentliche Briefings · sichere Hintergrundüberwachung · Frequenz-, Kosten- und Datenlimits · Benachrichtigungen · vollständige Oberfläche · Offline- und Fehlerverhalten · Export und Wiederherstellung · vollständige Abnahme auf **beiden** Mac-Architekturen (arm64 und x86_64, ADR-0018). Kanonische T1-Entitäten (Instrumente-Referenzen, Watchlists, Alarmregeln, Briefing-Definitionen, Provenienz) liegen in `personal/jarvis.db`; **Marktdaten bleiben Cache, nie kanonisch** (16 §2). Alarme und Briefings sind die erste produktive Anwendung des Automationsvertrags (ADR-0021); T1 enthält **keine R2-Fachoperation**.
3. **Aus T1 ausdrücklich ausgeschlossen:** echte Portfolioführung · Transaktionsimport · Tradingjournal · Performanceberechnung · Backtesting · Paper-Trading · Brokeranbindung · Ordervorbereitung · echte Orders · autonome Geldbewegungen.
4. **Offene Moduleinstiegsentscheidungen T1 (nicht erfunden, vor Baubeginn zu entscheiden):** Datenanbieter und Nachrichtenquellen · Assetklassen · Börsenabdeckung · Datenlizenzierung und Kosten · Aktualisierungsfrequenzen · Egress-/Sensitivitätsregeln für Cloud-Recherche (hängt an DEC-D09). Es existiert dafür noch keine belastbare Benutzer-, Lizenz- oder Anbieterentscheidung; keine wird vorweggenommen.
5. **DEC-D12 (Broker-Ziel):** bleibt **offen**. Die Stufung präzisiert den Auslöser: Entscheidung **vor dem Moduleinstieg T4** (nicht mehr „weit vor dem Trading-Modul", da T1–T3 brokerfrei sind). Der BrokerAdapter-Vertrag entsteht erst mit T4 (AV-33).

## Geprüfte Alternativen

- **Ein großes Trading-Modul (Daten bis Orders)** — verworfen: unabnehmbar groß, vermischt R0/R1-Intelligence mit R2-Execution.
- **T2 (Portfolio/Journal) vor T1** — verworfen (Eigentümer-Entscheid): T1 liefert den unmittelbaren täglichen Nutzen ohne Broker- und Transaktionsdaten.
- **Paper-Trading in T1** — verworfen: gehört zu T3/T4-Vorstufen; würde T1 unnötig an Order-Semantik koppeln.

## Konsequenzen

Modulkarte 16 führt Trading gestuft; „immer R2" bleibt für Orders/Execution (ab T4) und Risikoregel-Änderungen bestehen; T1 bleibt R0/R1. DEC-D12 im Register 17 mit präzisiertem Auslöser. Kein Trading-Code in diesem Auftrag.

## Verweise

Primärdokumente: 16 §1/§2/§4.2, 10 §1–§2, 12. Entscheidungen: DEC-045, DEC-049.

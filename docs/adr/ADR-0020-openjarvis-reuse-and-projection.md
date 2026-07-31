---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-1, AV-11, AV-12, AV-16, AV-25, AV-32, AV-33, AV-35
Zugehörige ADRs: ADR-0003, ADR-0004, ADR-0011, ADR-0013, ADR-0014, ADR-0017
Verwandte DEC-Einträge: DEC-004, DEC-007, DEC-010, DEC-044; berührt DEC-D09 (Sensitivitätsfilter der Projektion bleibt offen)
---

# ADR-0020: Übernahme der OpenJarvis-Reuse-Entscheidungen und kontrollierte Suchprojektion

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Am 2026-07-31 wurde der read-only durchgeführte **OpenJarvis Connector-, Capability- und Reuse-Audit** formal abgenommen. Sein Kanon besteht ausschließlich aus: (1) dem vollständigen Abschlussbericht (26 Kapitel), (2) der zweiten, vollständigen Fassung des Ergänzungs-, Korrektur- und Abnahmeberichts, (3) der kanonischen Fassung des Abnahme-Nachtrags, (4) dem letzten Korrekturblatt. Abgebrochene oder als nicht kanonisch bezeichnete Fassungen sind ausgeschlossen. Der Audit hat u. a. belegt: 25 Connectoren, 30 registrierte Channels und 2 unregistrierte Daemons ohne Löschsemantik und mit Klartext-Credentials; konkurrierende Kontakte-, Session-, Approval- und Audit-Wahrheiten; vier technische Releaseblocker; keine implementierte Projektion von der kanonischen Datenbank in den Suchindex.

## Entscheidung

1. **Übernahme des Audit-Kanons:** Die Einzelentscheidungen des Audits werden verbindlich übernommen und komponentenscharf im normativen Register **`docs/personal-jarvis/20-openjarvis-reuse-register.md`** geführt (DEC-044). Das Register ist die einzige kanonische Stelle dieser Entscheidungen; der Auditbericht selbst wird nicht als Parallelkopie in das Repository übernommen.
2. **Entscheidungsklassen (abschließend):** `KEEP` (unverändert als nachweislich stabile Infrastruktur behalten) · `REUSE` (wesentliche Bestandteile ohne grundlegende Neuausrichtung wiederverwenden) · `ADAPT` (als Grundlage verwenden, aber fachlich/technisch/sicherheitlich umbauen) · `PROJECT` (nur kontrollierte Projektion aus einer kanonischen Fachmoduldatenbank; nie eigene fachliche Wahrheit) · `REPLACE` (durch neue öffentliche, dokumentierte, fachlich saubere Anbindung ersetzen) · `REMOVE` (aus der Personal-Zielarchitektur entfernen). **`REMOVE` bedeutet Stilllegung/Deaktivierung in der Personal-Zielarchitektur; physisches Löschen von Upstream-Dateien erfolgt nur nach gesonderter Freigabe** (02 §2.4, 18 §3, ADR-0011). Wartungszustände (ruhend, Legacy, experimentell, verwaist, tot) sind keine Entscheidungsbestandteile.
3. **Kategorientrennung (verbindlich):** Jeder Bestandteil gehört genau einer Primärkategorie an: (a) Fachmodul, (b) Connector/externe Datenquelle, (c) kontrollierte Suchprojektion, (d) gemeinsame Infrastruktur, (e) Channel/Kommunikationsweg, (f) autonom ausführbare Fähigkeit. Mischformen werden analytisch getrennt (Register 20 §3).
4. **Kontrollierte Suchprojektion (Zielkomponente Z-1):** Suchindex und Agentenmemory sind **ausschließlich abgeleitet** und werden **niemals** eine zweite fachliche Wahrheit (AV-16, 06 §1). Für jede Fachdomäne gilt: Projektion nur kanonische DB → Index; Tombstone- und Löschweitergabe verpflichtend; Index jederzeit vollständig neu aufbaubar; **kein Rückschreiben** aus Index, Memory oder Tool in kanonische Fachdaten (AV-35); lokale Rollen und Metadaten bilden im Index keine eigene Wahrheit. Der Sensitivitätsfilter der Projektion (welche S1/S2-Felder projiziert werden) bleibt bis DEC-D09 offen; Zielspeicher (Weiternutzung `knowledge.db` oder eigener Personal-Index) wird beim ersten projizierenden Modul entschieden. Z-1 ist **nicht implementiert** und wird erstmals im Kontakte-Modul gebaut (Bestandteil von dessen Abschluss, modules/contacts.md §19).
5. **Sofort geltende Nutzungsgrenzen (aus dem Register):** Domänen-Connectoren (Kontakte/Kalender/Mail/Aufgaben) bleiben im Personal-Betrieb deaktiviert, bis das jeweilige Fachmodul seinen Adapter stellt; Provider-Mutationen laufen ausschließlich über den Personal-Approval-/Outbox-Pfad (Upstream-Pfade `execute_pending_actions`, `channel_send`, Channels K-01–K-32 sind für Personal-Daten gesperrt); Secrets ausschließlich Keychain (ADR-0004/0017); der Connect-Auto-Backfill gilt für Personal-Quellen als gesperrt.

## Geprüfte Alternativen

- **Auditbericht als eigenes Repository-Dokument einfrieren** — verworfen: Parallelkopie ohne kanonischen Pflegeort; das Register 20 hält nur die bindenden Entscheidungen nach.
- **Sofortiges physisches Löschen aller REMOVE-Pfade** — verworfen: verstößt gegen die eingefrorene Upstream-Baseline (ADR-0011) und 02 §2.4 (Hygiene nur mit gesonderter Freigabe).
- **Projektion sofort implementieren** — verworfen: AV-33; sie entsteht im Kontakte-Modul, das sie zwingend braucht.

## Konsequenzen

Register 20 wird normativer Bestandteil des Korpus (00 §1, 02 §2-Verweis). Die Boundary-Map 02 bleibt gültig; bei Komponentenkonflikten gilt die feinere Einzelentscheidung in 20. Die vier technischen Releaseblocker und vier Plattform-/Modulgates sind in DEC-050 und modules/contacts.md §19 festgeschrieben.

## Verweise

Primärdokumente: 20 (Register), 06 §1, 02 §2. Entscheidungen: DEC-044, DEC-050. Audit-Kanon: vier Berichtsteile vom 2026-07-31 (Sitzungsdokumente; Nachweisort der Entscheidungen ist das Register 20).

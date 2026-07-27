---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-5, AV-22
Zugehörige ADRs: ADR-0001 (ModelPort), ADR-0006
Verwandte DEC-Einträge: DEC-016; offen: DEC-D09
---

# ADR-0009: Cloud-Egress default-deny (fail-closed)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

„Cloud je Workspace" allein wäre zu grob: Ein Cloudmodell dürfte dann automatisch ganze Mails, Gesundheits-, Dokument-, Kontakt- oder Tradingdaten erhalten. Eine Klassifizierung, die allein dem aufrufenden Modul vertraut, wäre fehleranfällig — ein fehlerhaftes Modul könnte Sensibles als harmlos markieren. Das Produktversprechen ist local-first.

## Entscheidung

1. **Egress-Regelmodell:** Workspace × Capability × Datentyp × Sensitivitätsklasse (S0/S1/S2) × Modell/Provider × erlaubter Umfang (none | metadata | summary | full) × Redaction-Profil × dokumentierte Nutzerfreigabe. **Default: alles `none`** (lokal-only).
2. **Fail-closed-Klassifizierung:** deklarative Sensitivity-Labels an Datenobjekten/Feldern (Registrierungspflicht je Modul), Provenienz und Workspace werden mitgeführt; **unklassifizierte Daten gelten als S2 und werden blockiert**; der **EgressGuard** berechnet die effektiv höchste Klasse über den vollständigen Payload; Aufrufer dürfen erhöhen, nie herabsetzen; Redaction erzeugt neue, explizit klassifizierte Derivate.
3. **Absolute Non-Egress-Klasse:** Credentials, Auth-Tokens, Schlüsselmaterial — durch keine Regel freigebbar; Secret-Scanner als zweite Linie.
4. **Durchsetzung ausschließlich im ModelPort**; Freigaben sind R1, S2-/`full`-Freigaben R2; Audit speichert Metadaten und Hashes, nicht den Payload.
5. **Provider-Eigenschaften** (Prompt-Caching, Logging/Retention, Trainingsnutzung) sind Regelbestandteil und werden gegen Anforderungen abgeglichen.
6. **Modellantworten sind untrusted:** erneute Schema-Validierung; Ausgabe erbt die höchste Eingabe-Klassifizierung; keine Instruktionen/Endpunkte/Tool-Autorität aus Ausgaben; Freitext wird angezeigt, nie ausgeführt.

## Geprüfte Alternativen

- **Workspace-weite Cloud-Freigabe** — verworfen: zu grob, verletzt Datensparsamkeit.
- **Klassifizierung allein durch das aufrufende Modul** — verworfen: nicht fail-closed; ein Modulfehler würde zur Datenpanne.
- **Vollständiges Cloud-Verbot ohne Regelmodell** — verworfen: nähme dem Eigentümer bewusste, auditierte Einzelfreigaben.

## Konsequenzen

Lokale Modelle sind immer verfügbar; Cloud-Nutzen erfordert explizite, auditierte Grants; die S1/S2-Zuordnungsmatrix je Datentyp folgt mit dem ersten LLM-nutzenden Modul (DEC-D09).

## Verweise

Primärdokument: 12. Regeln: AV-5, AV-22.

---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10, AV-31
Zugehörige ADRs: ADR-0001, ADR-0012
Verwandte DEC-Einträge: DEC-002, DEC-012
---

# ADR-0002: Providerneutrale Capability-Verträge

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Fähigkeiten wie Kalender, Mail, Kontakte, Aufgaben, Life OS und Trading sollen providerneutral über austauschbare Adapter aufgebaut werden — keine anbieterbezogenen Kernmodule (kein festes IONOS-, Gmail- oder Broker-Modul). OpenJarvis besitzt keine neutrale Fähigkeits-Schicht: Konnektoren sind Lese-/Ingestion-Pfade, Aktionen leben getrennt als LLM-Tools; der Audit belegte daraus resultierende Provider-Duplikate (Gmail zweifach).

## Entscheidung

1. Je Fachbereich ein **kleiner, eigenständiger Capability-Vertrag** (`ContactsAdapter`, `CalendarAdapter`, `MailAdapter`, `BrokerAdapter`, …) mit eigener Registrierung — **keine universelle Mega-Schnittstelle**; Verträge entstehen erst mit ihrem Modul (AV-33).
2. Gemeinsame kleine Basistypen sind jetzt verbindlich: ProviderAccount, CredentialReference, CapabilityResult, CapabilityError, SyncState, ExternalIdentity, OperationRisk, ApprovalIntent, AuditEvent, IdempotencyKey (08 §2).
3. Das Kontenmodell trennt Provider / ProviderAccount / CredentialReference / CapabilityBinding / AdapterDefinition / ProviderCollection / Workspace-Zuordnung; ein Konto darf mehrere Bindings besitzen; keine fachliche Entität koppelt direkt an einen Provider (08 §1).
4. Einheitliche Vertragsanforderungen: Discovery, Fehlertaxonomie, Versionsbedingungen, Idempotenz, deklarierte Verifikationstiefe, Netzwerkregeln (08 §3).
5. **Apple-native Adapter sind gleichwertige Implementierungen** hinter denselben Verträgen (EventKit, Reminders, CNContactStore) über eine eng begrenzte native Bridge; Fachmodule kennen keine Apple-Frameworks; die Apple-Mail-App ist keine Mail-Datenquelle (08 §4).
6. **MCP** darf später eine Adapter-Implementierung sein, ist aber nicht der verbindliche Standard je Modul.

## Geprüfte Alternativen

- **Nur Tools als Schnittstelle** (Provider-Switch in Tools) — verworfen: kein programmatisches Modul-API, Ingestion bleibt getrennt, Duplikation wiederholt sich, Sync/Dedup ohne Zuhause.
- **MCP-Server je Fähigkeit als Standard** — verworfen: Prozess-/Latenz-Overhead je Fähigkeit, Bulk-Sync und UI-Integration unhandlich, zur Laufzeit nicht schlank; bleibt als optionale Adapter-Variante offen.
- **Vier ABCs auf Vorrat** — verworfen: verstößt gegen die Materialisierungsregel.

## Konsequenzen

Provider sind je Fähigkeit austauschbar (Contract-Suite + Live-Abnahme je Adapter); die Verträge werden das dauerhafteste API des Forks — Änderungen sind ADR-pflichtig (AV-31).

## Verweise

Primärdokument: 08. Betroffen: 16, 15 §1 Nr. 2. Regeln: AV-4, AV-10.

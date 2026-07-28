---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10 (zusätzlich berührt: AV-29 §4)
Zugehörige ADRs: ADR-0002, ADR-0016, ADR-0018
Verwandte DEC-Einträge: DEC-002, DEC-012, DEC-031, DEC-042, DEC-043
---

# 08 — Provider-, Konto- und Adaptermodell

## §1 Modelltrennung

Ein Konto kann mehrere Fähigkeiten bereitstellen (Beispiel: ein iCloud-Konto umfasst Kalender, Kontakte und Mail über unterschiedliche Technik). Das Modell trennt daher (Tabellen-Eigentümer: Einstellungen & Kontenverwaltung):

| Begriff | Bedeutung |
|---|---|
| **Provider** | Katalogeintrag („icloud", „fastmail", „google", „generic-caldav", „apple-system") mit deklarierten möglichen Fähigkeiten |
| **ProviderAccount** | konkrete Konteninstanz des Nutzers (Endpunkte, Zustand); auch der lokale macOS-Systemspeicher ist ein ProviderAccount des Providers „apple-system" |
| **CredentialReference** | zweckgebundener Verweis auf ein Keychain-Item, gehört zum ProviderAccount; ein Konto kann mehrere besitzen (z. B. getrennte App-Passwörter für CalDAV und IMAP) |
| **CapabilityBinding** | ProviderAccount × Fähigkeit (calendar/contacts/mail/tasks/broker/…) × AdapterDefinition × CredentialReference × Konfiguration; aktivierbar/deaktivierbar; Sync-Politik je Binding |
| **AdapterDefinition** | registrierte Implementierung („caldav", „apple-eventkit", „imap-smtp") mit Fähigkeit, Protokoll, Config-Schema, Discovery-Merkmalen |
| **ProviderCollection** | externe Sammlung innerhalb eines Bindings (konkreter Kalender, Adressbuch, Ordnerbaum); Auswahl, welche Sammlungen synchronisiert werden |
| **Workspace-Zuordnung** | auf Collection-Ebene (z. B. iCloud-Kalender „Arbeit" → Workspace Arbeit), mit Konto-Default |

**Regeln:** Ein ProviderAccount darf mehrere CapabilityBindings besitzen. **Keine fachliche Entität referenziert einen Provider direkt** — fachliche Datensätze kennen nur `workspace_id` und ihre externen Identitäten (die auf Binding/Collection zeigen) (AV-4).

## §2 Gemeinsame Basistypen

Jetzt verbindlich definiert (klein, providerneutral): `ProviderAccount`, `CredentialReference`, `CapabilityResult`, `CapabilityError`, `SyncState`, `ExternalIdentity`, `OperationRisk`, `ApprovalIntent`, `AuditEvent`, `IdempotencyKey`. **Fachverträge** (`ContactsAdapter`, `CalendarAdapter`, `MailAdapter`, `BrokerAdapter`, …) entstehen erst mit ihrem jeweiligen Modul (AV-33); keine ungenutzten ABCs auf Vorrat. MCP ist eine zulässige spätere Adapter-Implementierung, nie der verbindliche Standard (DEC-002).

## §3 Anforderungen an jeden Fachvertrag

1. **Operationen** mit deklarierter Risikoklasse und Idempotenz-Semantik; Create-Operationen akzeptieren client-generierte UIDs, wo das Protokoll es erlaubt (CardDAV/CalDAV-UID, Message-ID).
2. **Capability Discovery:** `capabilities(account)` meldet, welche Operationen der konkrete Provider/Account unterstützt; UI und Pipeline blenden Nichtunterstütztes aus — keine Scheinfunktionen (AV-3).
3. **Authentifizierung:** Adapter erhalten pro Aufruf genau das eine aufgelöste, zweckgebundene Secret vom Capability Service (`CredentialStore.resolve(reference, purpose)`, 09 §4); Adapter persistieren nie (AV-10).
4. **Synchronisation:** `changes_since(cursor)`-Delta, wo verfügbar (Sync-Token/CTag/HistoryId/UIDVALIDITY); sonst definierter Voll-Listen-Vergleich; Cursor als opakes Feld im SyncState (11 §3).
5. **Fehlernormalisierung** auf eine geschlossene Taxonomie: `AuthExpired` (→ Re-Auth-Fluss), `PermissionDenied`, `NotFound`, `Conflict` (Version/ETag), `RateLimited(retry_after)`, `TransientNetwork`, `ProviderInvalid`, `ValidationFailed`. Kein Durchsickern roher Provider-Exceptions.
6. **Konfliktbehandlung:** verpflichtende Versionsangabe (ETag o. ä.) bei Schreiboperationen; `Conflict` führt nie zu stillem Überschreiben (11 §3).
7. **Verifikationstiefe als Vertragsbestandteil:** Jeder Adapter deklariert je Operation, welche Tiefe er liefern kann (`verified` erreichbar? nur `provider_acknowledged`? nichts?); die Pipeline nutzt diese Deklaration (05 §6) — fehlender Read-back ist nur bei deklarierter Grenze zulässig, niemals stillschweigend.
8. **Netzwerkregeln:** Endpunkte stammen ausschließlich aus der Kontenkonfiguration (**nie aus LLM-Ausgaben**, AV-8); SSRF-Prüfung verpflichtend; private Adressen nur bei explizitem Nutzer-Opt-in je Konto (z. B. eigene Nextcloud im LAN).

## §4 Apple-native Adapter und Native Bridge

- Gleichwertige mögliche Adapter (Beispiele, endgültige Wahl je Modul offen — DEC-D10/D11): `AppleEventKitCalendarAdapter`, `AppleEventKitRemindersAdapter` (Fähigkeit tasks), `AppleContactsAdapter` (CNContactStore) — jeweils über eine **eng begrenzte native Bridge**, die ausschließlich innerhalb der Adapterschicht existiert. **Fachmodule kennen keine Apple-Frameworks** (AV-4). Bridge-Technik (PyObjC vs. Swift-Helper): DEC-D01.
- **TCC-Berechtigungsfluss** gehört zur Binding-Einrichtung; verweigerte Berechtigung ⇒ normalisierter Zustand `permission_denied` mit Anleitung (Modulzustand: 14 §4).
- Der Systemspeicher ist ProviderAccount des Providers „apple-system"; Collections sind die dort sichtbaren Kalender/Adressbücher; Änderungsverfolgung über Store-Change-Signale mit Voll-Diff-Fallback; Read-back ist lokal und damit sofort `verified` — die dahinterliegende iCloud-Synchronisation ist Apples Verantwortung und wird **nicht** als eigene Verifikation ausgegeben.
- **Mail:** ausschließlich offene Protokolle bzw. Provider-APIs (IMAP/SMTP bzw. JMAP). **Die Apple-Mail-App ist keine allgemeine Mail-Datenquelle** (DEC-012).
- **Belegte Capability-Grenzen der Apple-Kontakte-Bridge (ergänzt 2026-07-28 aus Spike G3a, ADR-0016 Punkt 8, DEC-043).** Sie werden über Capability Discovery (§3 Nr. 2) **deklariert**, nicht verschwiegen (AV-3):
  1. **Notizen (`note`).** Ohne besonderes Apple-Entitlement liefert der Store das Notizfeld nicht aus. Der Spike hat es angefordert und **nicht** erhalten — ohne Ausnahme, ohne Fehler. **`notesSupported` bleibt `false`.** Notizen werden **nicht** als produktiv verfügbare Fähigkeit zugesagt. Ein fehlendes Notizfeld darf **niemals** als leere Notiz interpretiert werden — weder beim Lesen noch beim Schreiben, weder im Diff noch im Konfliktvergleich; andernfalls würde eine Synchronisation vorhandene Notizen löschen. Ein Entitlement wird **nicht** ohne gesonderte Architekturentscheidung (eigener ADR) hinzugefügt.
  2. **Vereinheitlichte Kontakte.** Lesen und Identitätsbezug werden ausschließlich nach dem **belegten** API-Verhalten umgesetzt. **Verknüpfen und Trennen (Link/Unlink) werden nicht als mutierende Capability zugesagt**, solange keine öffentliche, freigegebene API dafür nachgewiesen ist; im geprüften SDK existiert keine. Der Mehrcontainer-/Unified-Livetest ist **offen** (15 §8); bis zu seinem Abschluss wird keine Schreibregel für vereinheitlichte Datensätze als belegt geführt.
  3. **Mutationsbindung.** Jede mutierende Operation ist an den **konkreten laufenden Vorgang bzw. die konkrete Freigabe** gebunden. Es gibt **keinen** globalen Aufräumpfad über ein Namenspräfix oder ein anderes Suchmuster — nur Datensätze, die derselbe Vorgang erzeugt hat, dürfen von ihm verändert oder gelöscht werden. **Fremde und vorbestehende Datensätze werden durch Test- oder Bereinigungslogik nie verändert.**
  4. **Unbekannter Mutationsausgang.** Bricht eine Mutation ohne eindeutige Antwort ab, gilt der Zustand `outcome_unknown`: **weder Erfolg noch Fehlschlag.** Es erfolgt **kein automatischer Wiederholungsversuch** und **keine automatische Bereinigung**; der Vorgang hält an und meldet den Zustand zur Klärung. Eine Umdeutung nach „fehlgeschlagen" oder „erfolgreich" ist unzulässig (05 §6, 11 §3).

- **Dual-Architektur-Pflicht (ADR-0018, DEC-042):** Für jede native macOS-Bridge — einschließlich des Swift-Contacts-Sidecars (ADR-0016) — muss für **beide** gleichwertigen Zielarchitekturen (Apple Silicon arm64 und Intel x86_64) nativer ausführbarer Code gebaut und nachgewiesen werden; Signierung und Packaging stellen sicher, dass beide Architekturen den korrekten nativen Code erhalten, und die Live-Abnahme erfolgt je Architektur auf echter Hardware (15 §7). Das Auslieferungsformat (gemeinsames Universal-2-Artefakt oder zwei architekturspezifische Pakete) ist dafür unerheblich und bleibt als **DEC-D17** offen. **Effektive Mindestversion ist macOS 12.3** (Contacts-API: `transactionAuthor` ab macOS 12, `shouldRefetchContacts` ab macOS 12.3). Die Bridge enthält **keine** architekturspezifische Fachlogik; Fachverträge, DTOs und Protokolle sind architekturneutral (AV-4). Architekturabhängigkeit ist ausschließlich in der Werkzeugschicht zulässig (Build-Skripte, Packaging, CI) und dort mit Host-Erkennung plus ausdrücklichem Override statt festverdrahteter Architektur.

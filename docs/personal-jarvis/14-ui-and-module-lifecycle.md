---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-3 (UI-Anteil), AV-9, AV-36
Zugehörige ADRs: ADR-0012
Verwandte DEC-Einträge: DEC-008, DEC-021
---

# 14 — UI-Architektur und Modul-Lifecycle

## §1 Grundsatz

Die bestehende React-/Tauri-App bleibt die produktive Oberfläche (DEC-008). Jedes Modul erhält ein **strikt gekapseltes Frontend-Verzeichnis**; gemeinsame Berührungen (Routing/Navigation) werden minimal gehalten. Kein Modul gilt als fertig, wenn es nur per CLI oder API funktioniert (19). Keine Platzhalter, Fake-Daten, leeren Menüpunkte oder nicht angebundenen Oberflächen (AV-3). ESLint/Prettier werden additiv für den Personal-Code eingeführt.

## §2 Build-Zeit vs. Laufzeit

- **Build-time-Registrierung:** Modul-Frontends werden statisch registriert (kompilierter Bestandteil der SPA; Modul-Manifest mit ID, Titel, Icon, Routen, Nav-Platz). **Kein dynamisches Nachladen beliebigen ungeprüften Frontend-Codes.**
- **Laufzeit-Readiness:** Das Backend meldet über `/v1/personal/system/modules` Readiness, Berechtigungen und verfügbare Adapter je Modul.
- **Navigationsregel:** sichtbar = **kompiliert ∧ betriebsbereiter erlaubter Zustand** (§4). Kein sichtbarer Menüpunkt ohne vollständiges Backend.

## §3 Globale Flächen

- **Kontenverwaltung** — ProviderAccounts, CapabilityBindings, ProviderCollections, Credential-Status, Sync-Gesundheit, Re-Auth; wächst vertikal mit jedem Modul.
- **Workspace-Umschalter** — globaler Filterkontext.
- **Approval-Center** — R2-Freigaben mit dauerhaften Intents; R1-Bestätigungen erscheinen inline am Ort der Aktion (05 §5, 10 §3).
- **Globale Suche** — erst mit ihrem Modul (16); vorher kein Menüpunkt.
- **Status/Fehler** — Konto-Statuschips, Outbox-Rückstand, Index-Lag, Konflikte, Kill-Switch-Zustand.
- **Chat** — bleibt die Upstream-Seite; Personal-Fähigkeiten erscheinen dort ausschließlich als Pipeline-Tools (Vorschau/Bestätigung im Chat-Fluss).

## §4 Modul-Lifecycle-Zustandsmaschine

Zustände: `not_installed · disabled · initializing · migration_required · configuration_required · permission_required · ready · degraded · error · shutting_down`

| Zustand | API erlaubt | Navigation | Blockiert / Anzeige |
|---|---|---|---|
| not_installed | keine | nein | — |
| disabled | Status | nein (nur Einstellungs-Liste) | Worker aus; Aktivierung über Einstellungen |
| initializing | Status | nein | Mutationen 503; Fortschritt in den Einstellungen |
| migration_required | Status + Diagnose | nein (System-Status, nicht Modul-Nav) | fail-closed; Anleitung (Backup/Migration ausführen) |
| configuration_required | Status + Konfigurations-Endpunkte | **nur sichtbar, wenn der Einrichtungsfluss vollständiger, echter Modulbestandteil ist** (Badge „Einrichten"); sonst nein | Fachoperationen blockiert; kein Platzhalter |
| permission_required | Status + Berechtigungs-Retry | ja, mit Hinweis | betroffene Bindings blockiert; Schritt-für-Schritt-Anleitung (z. B. TCC in den Systemeinstellungen) |
| ready | alle | ja | — |
| degraded | Lesen voll; Schreiben wo gesund | ja, mit Badge | je Binding/Collection blockierte Operationen + Ursache (Konto degraded, Index-Lag, Auth abgelaufen) |
| error | Status | ja, mit echter Diagnose-/Wiederherstellungsseite | alle Fachoperationen blockiert; konkrete Schritte |
| shutting_down | keine neuen Mutationen (503 retry-later) | unverändert | laufende Vorgänge enden geordnet |

**Aggregationsregeln:** Ausfall eines zwingenden Basisdienstes ⇒ `error`. Keine konfigurierten CapabilityBindings ⇒ `configuration_required`. Alle Bindings berechtigungsblockiert ⇒ `permission_required`; nur einige ⇒ `degraded`. Sync-/Collection-Störungen ⇒ `degraded` mit Detail je Collection. Module ohne Provider (rein lokal) überspringen bindingabhängige Zustände.

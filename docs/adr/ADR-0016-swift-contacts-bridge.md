---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10, AV-29
Zugehörige ADRs: ADR-0002; ergänzt durch ADR-0018 (Dual-Architektur, macOS 12.3)
Verwandte DEC-Einträge: DEC-031, DEC-042, DEC-043 (Spike-Abnahme); DEC-D17 (offen)
---

# ADR-0016: Native macOS-Kontakte-Bridge als Swift-Sidecar (DEC-D01)

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Das erste Fachmodul „Kontakte" benötigt einen produktiven Adapter gegen den macOS-Systemspeicher über `CNContactStore` (DEC-012, 08 §4). Der Code-Audit hat belegt: Es existiert **keine** PyObjC-Abhängigkeit (0 Treffer in `pyproject.toml`, `uv.lock`, `.venv`), **kein** Swift-Target, **kein** CNContact-Code. Der vorhandene Apple-Kontakte-Konnektor liest lediglich die AddressBook-SQLite read-only und ist damit weder schreibfähig noch vertragskonform. Als macOS-native Präzedenzfälle existieren AppleScript-Subprozesse (mit dokumentierter Locale-Fragilität) und ein gebündelter Sidecar (Ollama). DEC-D01 stand zwischen Swift-Sidecar, PyObjC in-process und AppleScript.

## Entscheidung

1. **Die native macOS-Kontakte-Bridge wird als dünner, signierter Swift-Sidecar mit JSON-Lines-Protokoll über stdio umgesetzt.** PyObjC und AppleScript werden für diesen Zweck verworfen.
2. **Verpflichtender technischer Spike vor der vollständigen Umsetzung.** Er muss nachweisen: (a) TCC-Berechtigungsverhalten und -Attribution, (b) Signierung/Notarisierungstauglichkeit, (c) `CNChangeHistory`-basierte Delta-Ermittlung, (d) Schreiben vereinheitlichter (verknüpfter) Kontakte, (e) Betrieb aus der **gepackten** Tauri-App.
3. **Scheitert der Spike, darf nicht automatisch auf PyObjC gewechselt werden.** In diesem Fall ist erneut die ausdrückliche Freigabe des Eigentümers einzuholen (per ADR).
4. **Dünnheits-Verbote (Vertragsbestandteil):** Der Sidecar übersetzt ausschließlich zwischen CN-Objekten und den DTOs des `ContactsAdapter`-Vertrags. Er enthält **keine** Fachlogik, **keine** Workspace-Logik, **keine** Merge-Entscheidungen, **keine** Risikobewertung, **keine** Audit-Entscheidungen und **keine** eigenständige kanonische Speicherung (AV-4, AV-10). Der Fachkern bleibt providerneutral und plattformunabhängig.
5. **Ehrliche Capability-Grenzen** werden über Capability Discovery deklariert (08 §3 Nr. 2/7) statt verschwiegen; ein deterministischer Voll-Diff-Fallback ist Pflichtbestandteil, falls keine stabile Delta-Synchronisation verfügbar ist (11 §3).
6. Die Toolchain-Erweiterung (Swift/Xcode-Kommandozeilenwerkzeuge auf der Zielplattform macOS) bleibt im Rahmen von AV-29; der Fachkern ist davon nicht betroffen und bleibt Linux-portabel.
7. **Dual-Architektur (ergänzt durch ADR-0018, DEC-042):** Für **beide** gleichwertigen macOS-Zielarchitekturen (Apple Silicon arm64 und Intel x86_64) muss nativer ausführbarer Sidecar-Code gebaut und nachgewiesen werden; Signierung und Packaging stellen sicher, dass beide Architekturen den korrekten nativen Code erhalten, und die Abnahme erfolgt je Architektur auf echter Hardware. Die **effektive Mindestversion ist macOS 12.3** (`CNSaveRequest.transactionAuthor` ab macOS 12, `CNSaveRequest.shouldRefetchContacts` ab macOS 12.3; Change-History-API ab macOS 10.15). Der Sidecar-Quellcode, das JSON-Lines-Protokoll und die DTOs bleiben architekturneutral; Architekturabhängigkeit existiert ausschließlich in Build- und Packaging-Werkzeugen. Der Spike nach Punkt 2 ist auf **beiden** Architekturen nachzuweisen; ein Ergebnis der einen Architektur gilt niemals automatisch für die andere, und Rosetta ersetzt keine native Abnahme (Matrix in 15 §7). Das Auslieferungsformat — gemeinsames Universal-2-Artefakt oder zwei getrennte architekturspezifische Pakete — bleibt als **DEC-D17** offen und wird durch diesen ADR nicht entschieden.

8. **Spike-Ergebnis G3a (ergänzt 2026-07-28, DEC-043):** Der nach Punkt 2 verpflichtende Spike ist auf **Apple Silicon arm64** durchgeführt und **bestanden**; **kein** Kill-Kriterium ist eingetreten. Damit gilt: der native Swift-Sidecar bleibt die vorgesehene Implementierungsrichtung, der eng begrenzte Objective-C-Shim bleibt **ausschließlich** für die aus Swift nicht erreichbare `CNChangeHistory`-API zulässig (reine Selektor-Weiterleitung, keine Fachlogik — Punkt 4 gilt unverändert), und **der Rückfall auf PyObjC wird nicht ausgelöst** (Punkt 3 bleibt für jeden künftigen Fehlschlag in Kraft). Der Spike **erlaubt den Beginn** der produktiven Kontakte-Implementierung. Er **erlaubt nicht** die Fertigmeldung des Moduls: Intel x86_64 bleibt gleichwertige produktive Zielplattform (Punkt 7, ADR-0018) und ist noch vollständig live abzunehmen; ebenso offen bleiben Spike-Ziel (d) — Schreiben vereinheitlichter Kontakte — und Spike-Ziel (e) — echte Kontakteoperation aus der gepackten Tauri-App — auf **beiden** Architekturen. Der Abnahmestand steht in **15 §8**; Spike-Evidenz ersetzt keine Abnahmezeile (15 §7 Nr. 4, AV-3, 19).

## Spike-Ergebnis G3a (2026-07-28)

**Auf arm64 live belegt:** nativer arm64-Build mit `minos 12.3` · Erreichbarkeit der Change-History-API über den genehmigten Objective-C-Shim · JSON-Lines-Protokoll (Handshake, `ping`, `caps`, grazioser Shutdown) · Hardened Runtime, **zertifikatsbasierte** Designated Requirement, Sidecar **ohne** Entitlements, eigener `NSContactsUsageDescription` · TCC-Autorisierung **auf den Sidecar** attribuiert · Containerzugriff · vollständiger Enumerate-Lesepfad · CRUD · Feldabdeckung · Erkennung einer extern ausgelösten Änderung · Change History mit Echo-Unterdrückung eigener Änderungen · definierte Behandlung ungültiger Token · Voll-Diff-Fallback · Delete · laufgebundene Bereinigung · Me-Karte und Fremdkontakte nachweislich unangetastet. Bilanz: **28 ausführbare Gates bestanden, 0 fehlgeschlagen, 1 mangels zweitem Container nicht ausführbar**; **187/187** kontaktfreie Prüfungen grün.

**Auf x86_64 bisher belegt:** nativer x86_64-Build mit `minos 12.3` · Objective-C-Shim · Protokolltests · T3-Ad-hoc- und T4-zertifikatssigniertes Packaging · Hardened Runtime und Designated Requirement · TCC-Autorisierung im Testbenutzer · **kontaktfreier** App-/Sidecar-Handshake aus der gepackten App.

**Weiterhin offen** (keiner dieser Punkte gilt als bestanden): der vollständige Enumerate-, CRUD-, Change-History-, Voll-Diff-, Cleanup- und Feldabdeckungs-Livelauf auf x86_64 · der Mehrcontainer-/Unified-Livetest auf **beiden** Architekturen · die echte Kontakteoperation aus der gepackten App auf **beiden** Architekturen · die vollständige TCC-Persistenzmatrix · die produktive Datenbank-, Sync-, API- und UI-Integration · **DEC-D17** (Auslieferungsformat).

**Evidenz** (nicht dupliziert, nur verwiesen): [`docs/testing/contacts-bridge-spike-handoff-2026-07-27.md`](../testing/contacts-bridge-spike-handoff-2026-07-27.md) · [`contacts-bridge-intel-t3-t4-evidence-2026-07-27.md`](../testing/contacts-bridge-intel-t3-t4-evidence-2026-07-27.md) · [`contacts-bridge-intel-tcc-authorization-gate-2026-07-27.md`](../testing/contacts-bridge-intel-tcc-authorization-gate-2026-07-27.md) · [`contacts-bridge-create-timeout-diagnostics-2026-07-27.md`](../testing/contacts-bridge-create-timeout-diagnostics-2026-07-27.md) · [`contacts-bridge-platform-authorization-profile-2026-07-28.md`](../testing/contacts-bridge-platform-authorization-profile-2026-07-28.md) · [`contacts-bridge-arm64-enumerate-sigabrt-2026-07-28.md`](../testing/contacts-bridge-arm64-enumerate-sigabrt-2026-07-28.md) · [`contacts-bridge-arm64-phase-b-live-2026-07-28.md`](../testing/contacts-bridge-arm64-phase-b-live-2026-07-28.md). Spike-Quellen: [`spikes/contacts-bridge-g3a/`](../../spikes/contacts-bridge-g3a/) — Spike-Code, **kein** Produktcode.

## Geprüfte Alternativen

- **PyObjC in-process** — verworfen: neue, im Lock-File bislang nicht vorhandene Abhängigkeitsfamilie; diffuse TCC-Attribution auf den Python-/uv-Prozess; umständliches Bridging der Change-History-Enumeratoren; keine eigene Signierbarkeit. Bleibt als Rückfalloption nur nach ausdrücklicher neuer Freigabe (Punkt 3).
- **AppleScript/`osascript`** — verworfen: strukturell fragile, locale-abhängige Textausgabe (im Bestand dokumentiert), für strukturierte Kontaktdatensätze und Schreiboperationen ungeeignet.
- **Weiterverwendung des AddressBook-SQLite-Lesepfads** — verworfen: read-only, keine Provider-Verifikation, keine Tombstones, widerspricht DEC-012 und dem Verbot einer nur lesenden Vorstufe (AV-3).

## Konsequenzen

Klare Prozess- und Signaturgrenze, isoliert testbar (Golden-JSON gegen den Sidecar; Contract-Suite gegen Fake und echt); dafür eine zweite Sprache im Repository, deren Umfang durch die Dünnheits-Verbote klein bleibt. Der Spike ist ein eigenes Gate des Kontakte-MASTER; ohne bestandenen Spike beginnt keine Adapter-Umsetzung.

## Verweise

Primärdokumente: 08 §4 (Native Bridge, Capability-Grenzen), 11 §3, 15 §7 (Dual-Architektur-Abnahme), 15 §8 (Abnahmestand Kontakte), 16 §4 (Startkriterien), 17 (DEC-D01, DEC-D17), 19 §10. Regeln: AV-3, AV-4, AV-10, AV-29. Entscheidungen: DEC-031, DEC-042 (ADR-0018), DEC-043 (Spike-Abnahme); offen: DEC-D17 (Auslieferungsformat).

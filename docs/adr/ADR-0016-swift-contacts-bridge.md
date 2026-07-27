---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: personal-jarvis-architecture-v3-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-10, AV-29
Zugehörige ADRs: ADR-0002
Verwandte DEC-Einträge: DEC-031
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
6. Die Toolchain-Erweiterung (Swift/Xcode-Kommandozeilenwerkzeuge auf der Primärplattform macOS) bleibt im Rahmen von AV-29; der Fachkern ist davon nicht betroffen und bleibt Linux-portabel.

## Geprüfte Alternativen

- **PyObjC in-process** — verworfen: neue, im Lock-File bislang nicht vorhandene Abhängigkeitsfamilie; diffuse TCC-Attribution auf den Python-/uv-Prozess; umständliches Bridging der Change-History-Enumeratoren; keine eigene Signierbarkeit. Bleibt als Rückfalloption nur nach ausdrücklicher neuer Freigabe (Punkt 3).
- **AppleScript/`osascript`** — verworfen: strukturell fragile, locale-abhängige Textausgabe (im Bestand dokumentiert), für strukturierte Kontaktdatensätze und Schreiboperationen ungeeignet.
- **Weiterverwendung des AddressBook-SQLite-Lesepfads** — verworfen: read-only, keine Provider-Verifikation, keine Tombstones, widerspricht DEC-012 und dem Verbot einer nur lesenden Vorstufe (AV-3).

## Konsequenzen

Klare Prozess- und Signaturgrenze, isoliert testbar (Golden-JSON gegen den Sidecar; Contract-Suite gegen Fake und echt); dafür eine zweite Sprache im Repository, deren Umfang durch die Dünnheits-Verbote klein bleibt. Der Spike ist ein eigenes Gate des Kontakte-MASTER; ohne bestandenen Spike beginnt keine Adapter-Umsetzung.

## Verweise

Primärdokumente: 08 §4, 11 §3, 17 (DEC-D01). Regeln: AV-4, AV-10, AV-29. Entscheidung: DEC-031.

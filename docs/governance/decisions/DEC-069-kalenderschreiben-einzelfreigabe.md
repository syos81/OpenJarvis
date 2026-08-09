---
DEC-ID: DEC-069
Titel: Kalenderschreiben produktiv zugelassen: einzelfreigegebene Mutationen über den getrennten Schreibpfad
Status: accepted
Regel-Alias: Kalenderschreiben
Registerpfad: refs/governance/dec-reservations
Block: B3
---

# DEC-069 — Kalenderschreiben produktiv zugelassen: einzelfreigegebene Mutationen über den getrennten Schreibpfad

## Kontext

DEC-055 begrenzte den Kalender-Fundament-Spike auf rein lesende Arbeit; die
CLAUDE.md-Hartgrenze verbot jede Termin-Mutation ohne Bestätigung; die
K1-Definition führt die Schreib-**Parität** als eigene, weiterhin offene
Entscheidung (Platzhalter `{{DEC_ID_CALENDAR_WRITE_PARITY}}`). B1/B2 haben
den produktiven read-only Pfad und die Monatsansicht live belegt. Der
Eigentümer hat für B3 entschieden, das Schreiben jetzt produktiv zuzulassen.

## Entscheidung (normativ)

Kalenderschreiben ist produktiv zugelassen — direkt gegen reale Kalender, für
Anlegen, Ändern und Löschen — ausschließlich über den dafür freigegebenen,
vom Lese-Sidecar getrennten Kalender-Mutationspfad im verantwortlichen
App-Prozess, nach dem bewährten Claim-Settle-Grundsatz des Kontaktmoduls.
Verbindlich dabei: (1) Jede einzelne Mutation benötigt die ausdrückliche
Eigentümerfreigabe; eine Freigabe ist einmalig, an genau eine Operation und
deren Payload-Digest gebunden und nicht übertragbar; Update und Delete binden
zusätzlich Eventidentität und den Fingerprint des vorgelegten
Ausgangszustands; eine generelle Schreib-Pauschalfreigabe existiert nicht.
(2) Vor der ersten echten Mutation ist der Zielbestand gesichert und die
Sicherung verifiziert; ohne verifizierte Sicherung keine Mutation. (3) Delete
verlangt einen unmittelbaren Re-Read vor der Ausführung und bricht bei
verändertem Fingerprint ohne Mutation ab; dasselbe Verhalten gilt für Update,
soweit der Pfad es trägt. (4) Die Live-Abnahme läuft gestuft
Create → Update → Delete mit Halt und Eigentümerbestätigung nach jeder Stufe.
(5) Der produktive Lese-Sidecar bleibt read-only, seine
Mutationssymbol-Sperre bleibt bestehen; eine Mutation ohne gültige Freigabe
darf den nativen Schreibpfad nicht erreichen.

## Geltungsbereich

Der Kalender-Mutationspfad der Jarvis-App auf dieser Linie (Create, Update,
Delete realer Termine). Die frühere generelle Read-only-Grenze (DEC-055 —
Kalender-Fundament-Spike; CLAUDE.md-Hartgrenze) ist genau in diesem Pfad
aufgehoben und bleibt außerhalb davon bestehen.

## Ausdrücklich nicht geregelt

Kein Chat- oder Agentenweg zum Schreiben; keine arm64-Abnahme; keine
Schreib-Parität — der K1-Platzhalter `{{DEC_ID_CALENDAR_WRITE_PARITY}}`
bleibt unverändert offen; keine Recurrence-/Teilnehmer-/Einladungs-Semantik
über das verlustfrei getragene Modell hinaus.

## Mechanische Durchsetzung

Read-only-Sidecar-Invariante (b1 readonly-Modus, Symbolsperre im Build samt
Negativfixture); Freigabe-, Digest- und Fingerprintbindung im
B3-Mutationspfad mit Prüfungen im B3-Gateblock (Mutation ohne Freigabe fällt,
Konflikt bricht ab, Backup-Nachweis vor erster Mutation); die
Prozessverantwortung liegt beim signierten App-Bundle (TCC-Gegenprobe B1).

## Herkunft

Bindende Eigentümerentscheidung für B3 (Auftrag vom 2026-08-09), wörtlich:
produktives Zulassen, Einzelfreigabe je Mutation, Sicherung vor der ersten
Mutation, Delete mit unmittelbarem Re-Read und Abbruch bei Zustandsänderung,
gestufte Live-Abnahme mit Halt. Verfahrensvorbild ist der belegte
Kontakte-Mutationskanal (ADR-0025, „Architektur der
Apple-Contacts-Provider-Mutationen (Create/Update/Delete)"; ADR-0026, „Der
App-Prozess-Mutationskanal (Backend → Claim → Frontend → Tauri →
Contacts.framework → Settle)"). DEC-055 wird nicht umgeschrieben; diese
Entscheidung steht daneben und hebt die Lesegrenze nur im definierten
Mutationspfad auf.

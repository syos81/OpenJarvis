---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-5, AV-22
Zugehörige ADRs: ADR-0009
Verwandte DEC-Einträge: DEC-016
---

# 12 — Cloud-Egress und Modell-Sicherheit

## §1 Sensitivitätsklassen und Labels

- Klassen: **S0** (technisch/nicht personenbezogen) · **S1** (personenbezogen) · **S2** (besonders sensibel: Gesundheit, Finanzen/Trading, private Dokumentinhalte). **Credentials, Auth-Tokens und Schlüsselmaterial stehen außerhalb jeder Klasse und sind absolut non-egress** — durch keine Regel freigebbar.
- **Deklarative Labels an der Quelle:** Jedes Modul registriert für seine Entitätstypen ein Feld-Label-Schema (S0/S1/S2). Alles, was einen Cloud-Abfluss quert, ist ein **EgressPayload aus etikettierten Fragmenten** mit Provenienz (Modul, Entitätstyp, Workspace).
- **Fail-closed:** Unklassifizierte Inhalte gelten als **S2 und werden blockiert.**
- Die Zuordnungsmatrix einzelner Datentypen zu S1/S2 ist bewusst offen (DEC-D09) und wird mit dem ersten LLM-nutzenden Modul vorgelegt.

## §2 EgressGuard

- Der Guard berechnet die **effektive Klasse als Maximum über alle Fragmente** des vollständigen Payloads — nicht das aufrufende Modul.
- Ein aufrufendes Modul darf die Sensitivität **erhöhen, niemals herabsetzen.**
- **Redaction** erzeugt ein neues, explizit klassifiziertes Derivat-Fragment mit Verweis auf das Original; die Klassifizierung des Originals bleibt unverändert; die Ableitung wird protokolliert.
- Zweite Verteidigungslinie: Secret-Scanner am Durchsetzungspunkt.

## §3 Egress-Regeln

- Form: **Workspace × Capability × Datentyp × Sensitivitätsklasse × Modell/Provider × erlaubter Umfang (none | metadata | summary | full) × Redaction-Profil × dokumentierte Nutzerfreigabe.**
- **Default: lokal-only** — jede Cloud-Regel steht auf `none`, bis eine Freigabe erteilt ist. Freigaben sind R1; **Freigaben für S2 oder Umfang `full` sind R2** (Approval-Center). Ein Cloudmodell erhält nie automatisch ganze Mails, Gesundheitsdaten, Dokumente, Kontakte oder Tradingdaten, nur weil ein Workspace grundsätzlich Cloud-Nutzung erlaubt.
- **Provider-Eigenschaften sind Regelbestandteil:** Jeder Modell-Provider-Eintrag deklariert Prompt-Caching, Logging/Retention und Trainingsnutzung; Egress-Regeln können Eigenschaften **verlangen** (z. B. S1-Summary nur an Provider ohne Trainingsnutzung); der Durchsetzungspunkt gleicht Anforderung gegen Eigenschaften ab.
- Lokale Modelle sind immer zulässig; der Standard für Personal-Daten ist lokal-only. Auch Sprachverarbeitung folgt dem Local-first-Default (lokale STT/TTS; Cloud-Speech nur explizit und gemäß §5) (DEC-016).

## §4 Audit bei Cloud-Abfluss

Gespeichert werden Regel-ID, effektive Klasse, Provider/Modell, Umfang, Fragment-Hashes und Token-Zahlen — **nicht automatisch der sensible Payload.**

## §5 Durchsetzung

Der **EgressGuard** ist die einzige Durchsetzungsinstanz für **jeden Cloud-Abfluss von Personal-Daten**. Für LLM-Aufrufe ist der **ModelPort** (04 §2) der verpflichtende Durchsetzungspunkt: Jeder `complete()`-Aufruf trägt den EgressContext; die Registrierung der Labels ist Modulpflicht, Berechnung und Durchsetzung sind Portpflicht; Verstöße werden blockiert und auditiert. **Dasselbe gilt verbindlich für jeden anderen Cloud-Dienst mit Personal-Daten — insbesondere für spätere Cloud-STT- und Cloud-TTS-Dienste:** Auch diese Aufrufe müssen vor Ausführung durch denselben EgressGuard geprüft werden. Lokale Speech-Verarbeitung bleibt Standard; Credentials und Schlüsselmaterial bleiben absolut non-egress. Die konkrete SpeechPort-/Adaptertechnik wird erst mit dem Voice-Modul materialisiert (AV-33); diese Regel entscheidet **keinen** konkreten Cloud-Speech-Anbieter.

## §6 Behandlung von Modellantworten (untrusted)

- Strukturierte Ausgaben werden erneut schema-validiert (genau ein präziser Retry, danach Übergabe an die UI; 05 §4 Nr. 2).
- Die Ausgabe erbt die **höchste Eingabe-Klassifizierung** als Provenienz-Label.
- Aus Modellausgaben werden **niemals** Instruktionen, Endpunkte oder Tool-Autorität abgeleitet — sie füllen ausschließlich den erwarteten Schema-Slot des laufenden Pipeline-Schritts (AV-8; Prompt-Injection-Trennung).
- Freitext wird angezeigt, nie ausgeführt; Links/Endpunkte aus Ausgaben werden nie automatisch verfolgt.

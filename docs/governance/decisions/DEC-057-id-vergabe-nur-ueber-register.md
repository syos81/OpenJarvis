---
DEC-ID: DEC-057
Titel: DEC-/ADR-Vergabe ausschließlich über das kanonische Reservierungsregister
Status: accepted
Regel-Alias: R2
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-057 — DEC-/ADR-Vergabe ausschließlich über das kanonische Reservierungsregister

## Kontext

Zwei fortlaufende Linien vergaben Nummern gegen eingefrorene Stände; eine heute freie Nummer ist nicht gegen die künftige Belegung derselben Serie frei (config/gates/k1/calendar-k1-definition.json, separate_write_decision). B0c baute das Anhängeregister mit Hashkette auf refs/governance/dec-reservations; B0g nahm es real in Betrieb und importierte die Vergabebestände beider Linien als Genesis.

## Entscheidung (normativ)

Eine DEC- oder ADR-Nummer gilt ausschließlich dann als vergeben, wenn das kanonische Register refs/governance/dec-reservations für sie einen gültigen assigned-Zustand führt, erreicht über reserved → assigned nach dem Registervertrag (Append-only, Hashkette, Compare-and-Swap, Ein-Ereignis-Commits). Werkzeuge melden freie Nummern, vergeben aber nie; eine Erwähnung außerhalb einer Registertabellenzeile vergibt nichts; Reservierung und Vergabe sind Eigentümerhandlungen (Ref-Push nur durch den Eigentümer).

## Geltungsbereich

Alle DEC- und ADR-Nummern beider Linien; alle künftigen Vergaben.

## Ausdrücklich nicht geregelt

Der fachliche Inhalt der nummerierten Entscheidungen; die Auflösung des Ambient-Platzhalters {{DEC_ID_AMBIENT_INTERACTION_V1}} (DEC-050-gebunden, unverändert).

## Mechanische Durchsetzung

tools/decreg (Modell, Store mit CAS, Scanner mit strukturellem Vergabebegriff, plan-push druckt exakt einen Eigentümerbefehl und führt nichts aus); Gates of-register-model, of-register-tool, of-scanner-method; Guard-Verstoßkorpus für Pushes auf die Governance-Ref; ab B0g b0g_checks --mode register.

## Herkunft

allocation_rule-Token R2 in config/gates/k1/calendar-k1-definition.json (29fc013, B0b); Werkzeug und Vergabebegriff aus B0c (docs/governance/b0c-handoff.md §5, config/gates/history/b0c-stop2-correction.json); Genesis und Erstbetrieb in B0g.

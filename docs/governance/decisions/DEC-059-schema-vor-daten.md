---
DEC-ID: DEC-059
Titel: Schema vor Daten: jede Konfiguration an genau einen akzeptierenden Leser gebunden
Status: accepted
Regel-Alias: R4
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-059 — Schema vor Daten: jede Konfiguration an genau einen akzeptierenden Leser gebunden

## Kontext

Eine Konfigurationsdatei, die ein Feld trägt, das ihr Leser noch nicht akzeptiert, erzeugt stille Drift; im Guard-Kontext sperrt eine unlesbare Konfiguration die Sitzung vollständig aus (fail-closed).

## Entscheidung (normativ)

Wird ein Konfigurationsformat erweitert, ist der akzeptierende Leser oder Validator zuerst wirksam, spätestens im selben Commit. Keine Konfigurationsdatei darf ein Feld tragen, das ihr deklarierter Leser noch nicht akzeptiert. Jede Konfigurationsdatei unterhalb der Abdeckungswurzeln ist an genau einen Leser gebunden, jedes Gate lädt sie mit diesem Leser, und ein Bindungsfehler fällt den Block. Die Bindungsdatei bindet sich selbst; R4 kennt keine Ausnahme für sich.

## Geltungsbereich

Alle Dateien unter den deklarierten Abdeckungswurzeln (derzeit config und tools/guard).

## Ausdrücklich nicht geregelt

Das Fenster zwischen Leser und Daten während einer aktiven Migration (DEC-063, R8); Nicht-Konfigurationsartefakte.

## Mechanische Durchsetzung

pf-/tg-/of-config-loaders (tools/gates/configload.py über config/governance/config-loaders.json); tests/tooling/gates/test_config_loaders.py.

## Herkunft

statement-Feld in config/governance/config-loaders.json (6feb7ce, B0c, Position 1). Die verkürzte Wiedergabe im Guard-Vertrauensmodell war eine Parallelwahrheit und ist seit B0g reine Referenz.

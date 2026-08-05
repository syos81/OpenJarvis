---
Status: normativ (B0a-2 Governance); Nachtrag zu § 6 der Kalender-Implementierungsbaseline
Maschinelle Quelle: config/governance/decision-collisions.json
Zitatregistry: config/governance/decision-citations.json
---

# B0a-2 — DEC- und ADR-Kollisionen (dokumentiert, nicht aufgelöst)

## §1 Geltung und Verhältnis zur Kalender-Baseline

Dieses Dokument ist der **Nachtrag zu § 6 der Kalender-Implementierungsbaseline**
`docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md` auf der Linie
`spike/calendar-foundation-intel-2026-08-04@8e6e206`. Dort ist die ADR-Doppelvergabe
0019/0020 bereits befundet und mit einem Umnummerierungsplan versehen; § 6 dokumentiert
auch die Merge-Base `d037cb6` beider Linien.

Die Kalender-Baseline ist von `tooling/gates-v1` aus **nicht erreichbar**: Dieser
Branch zweigt von der Merge-Base `d037cb6` ab und enthält die Datei nicht. Merge,
Rebase und Cherry-pick sind in B0a-2 ausdrücklich verboten. Der Nachtrag entsteht
deshalb hier, an genau einer Stelle, und wird durch die eng begrenzte spätere
Tooling-Integration (`docs/governance/b0a-2-tooling-merge-addendum.md`) in die
Kalenderlinie geführt. Es entsteht **keine zweite Wahrheit**: § 6 wird nicht kopiert,
sondern um die DEC-Doppelvergaben ergänzt.

## §2 Befund

Beide Linien haben nach der Merge-Base `d037cb6` unabhängig voneinander dieselben
Nummern vergeben. Betroffen sind fünf DEC-Nummern und zwei ADR-Nummern.

**Linien und belegte Stände:**

| Linie | Referenz | Stand |
|---|---|---|
| kanonische Linie | `jarvis/rebuild-v1` | `c222601` |
| Kontakt-/Kalenderlinie | `handoff/contacts-read-flow-2026-07-29` | `1f03bfa` |
| Fortführung derselben Linie | `spike/calendar-foundation-intel-2026-08-04` | `8e6e206` |

## §3 DEC-Doppelvergaben

Primärstelle beider Seiten ist jeweils `docs/personal-jarvis/decisions-register.md`
am angegebenen Stand.

| Nummer | Belegung auf `jarvis/rebuild-v1@c222601` | Belegung auf der Kontakt-/Kalenderlinie |
|---|---|---|
| `DEC-044` | DEC-044 (jarvis/rebuild-v1@c222601, „Übernahme des OpenJarvis-Reuse-Audit-Kanons") | DEC-044 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Architektur der Apple-Contacts-Provider-Mutationen eingefroren") |
| `DEC-045` | DEC-045 (jarvis/rebuild-v1@c222601, „Verbindliche Modulreihenfolge bis Modul 3") | DEC-045 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „App-Prozess-Mutationskanal eingefroren") |
| `DEC-046` | DEC-046 (jarvis/rebuild-v1@c222601, „Autonomie- und Hintergrundaktionsmodell") | DEC-046 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „DEC-D06 entschieden: keine native R2-Zweitbestätigung") |
| `DEC-047` | DEC-047 (jarvis/rebuild-v1@c222601, „KI-Arbeit, Internet, Browser- und App-Steuerung als verbindliches Zielbild") | DEC-047 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Intel-Zweig des Kontaktmoduls eingefroren") |
| `DEC-048` | DEC-048 (jarvis/rebuild-v1@c222601, „Hausverwaltungs-Systemgrenzen und Workspace-Sicherheitskontexte") | DEC-048 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Kalender-Fundament-Spike (Intel) freigegeben und begrenzt") |

Alle fünf Einträge der Kontakt-/Kalenderlinie sind bereits auf
`handoff/contacts-read-flow-2026-07-29@1f03bfa` belegt und werden auf
`spike/calendar-foundation-intel-2026-08-04@8e6e206` unverändert fortgeführt.

## §4 ADR-Doppelvergaben

| Nummer | Belegung auf `jarvis/rebuild-v1@c222601` | Belegung auf der Kontakt-/Kalenderlinie |
|---|---|---|
| `ADR-0019` | ADR-0019 (jarvis/rebuild-v1@c222601, „Verbindliche Modulreihenfolge und 100-Prozent-Modulvollendung") · Primärstelle `docs/adr/ADR-0019-module-sequence-and-total-completion.md` | ADR-0019 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Architektur der Apple-Contacts-Provider-Mutationen (Create/Update/Delete)") · Primärstelle `docs/adr/ADR-0019-provider-mutation-architecture.md` |
| `ADR-0020` | ADR-0020 (jarvis/rebuild-v1@c222601, „Übernahme der OpenJarvis-Reuse-Entscheidungen und kontrollierte Suchprojektion") · Primärstelle `docs/adr/ADR-0020-openjarvis-reuse-and-projection.md` | ADR-0020 (handoff/contacts-read-flow-2026-07-29@1f03bfa, „Der App-Prozess-Mutationskanal (Backend → Claim → Frontend → Tauri → Contacts.framework → Settle)") · Primärstelle `docs/adr/ADR-0020-app-process-mutation-channel.md` |

Die ADR-Nummern 0021 bis 0024 sind ausschließlich auf `jarvis/rebuild-v1@c222601`
belegt und deshalb nicht kollidiert. Die ADR-Nummern 0001 bis 0018 sind auf beiden
Linien identisch belegt.

**Zitierregel:** In diesem und in jedem anderen normativen Governance-Dokument wird
jede DEC- und ADR-Nummer im Fließtext ausschließlich qualifiziert genannt, also mit
Linie einschließlich belegtem Stand und exaktem Titel. Eine reine Nummer ist nur als
Bezeichner in Codespannen und Tabellenschlüsseln zulässig; das Gate prüft das
mechanisch.

## §5 Was B0a-2 ausdrücklich nicht tut

B0a-2 **dokumentiert** die Kollisionen und **löst sie nicht auf**. Verboten bleiben
bis zur integrierten Auflösung:

* keine Umnummerierung,
* keine neue kanonische ID,
* kein stilles Löschen einer Seite,
* keine Erklärung einer Linie zur allein gültigen Belegung,
* keine neue ADR-Datei und keine ADR-Reservierung,
* keine Umdeutung einer bestehenden Entscheidung.

Der in § 6 der Kalender-Baseline beschlossene Umnummerierungsplan für die
Mutationslinie bleibt unverändert gültig und wird von B0a-2 weder ersetzt noch
vorweggenommen.

## §6 Wirkung auf die Gates

**B0a-2-Abschluss:** Bekannte und hier vollständig dokumentierte Kollisionen
verhindern den begrenzten Abschluss nicht. Das Gate schlägt jedoch fehl, wenn eine
bekannte Seite fehlt, Titel, Linie oder Primärstelle falsch zugeordnet sind, eine
zusätzliche Kollision unbemerkt bleibt, eine Kollision stillschweigend bereinigt
wurde, eine neue DEC- oder ADR-ID vergeben oder eine bestehende ID umgedeutet wurde.
Die Prüfung vergleicht dazu die vollständigen ID-Bestände beider Linien mechanisch
gegen dieses Register.

**Spätere Integration:** Das Integrations-Gate schlägt fehl, solange eine ID doppelt
vergeben ist, eine normative Zuordnung mehrdeutig ist oder die integrierte Neuvergabe
beziehungsweise Umnummerierung nicht vollständig vollzogen wurde. B0a-2 löst diesen
Integrationsblocker nicht auf.

---
Status: normativ (B0a-3 Abschluss-Handoff für B0b)
Erzeugt aus: maschinelle Gate-Ergebnisse, sanitierte Evidenz, Git-Daten, deklarative Manifeste
Zielbranch: spike/calendar-foundation-intel-2026-08-04
---

# B0b-Handoff — verbindlicher Ausgangszustand

Dieses Handoff liefert B0b den Ausgangszustand ohne erneute Rekonstruktion.
Es nimmt den B0b-Auftrag **nicht** vorweg und trifft keine fachliche
Entscheidung.

## §1 Git-Zustand

| Größe | Wert |
|---|---|
| Zielbranch | `spike/calendar-foundation-intel-2026-08-04` |
| Kalender-Ausgangsstand (erster Parent) | `8e6e2063fc3b41db9c4a434a54037eb64ac47f0a` |
| Tooling-Abschlussstand (zweiter Parent) | `4e471446f98d8cefe71a8c98f086e7fd243f3e44` |
| Integrationsart | echter Merge mit zwei Eltern, kein Rebase, kein Squash, kein Cherry-pick |
| Pushstatus | `not_performed_owner_action` |

Der finale integrierte HEAD steht im Abschlussbericht dieses Blocks und ist
über `git rev-list --parents -n 1 HEAD` mit beiden Eltern nachweisbar; das
Gate `of-merge-topology` prüft Parent-Anzahl und Parent-Reihenfolge
maschinell.

## §2 Guard-Basis

| Größe | Wert |
|---|---|
| kanonische Linie | `jarvis/rebuild-v1` @ `c222601` |
| Kalenderlinie | `spike/calendar-foundation-intel-2026-08-04` |
| Ableitung | `git merge-base --all` beider Entscheidungslinien |
| Anzahl Merge-Bases | 1 |
| abgeleitete Guard-Basis | `d037cb67502ab7fdcef95161bdbf2857181d0354` |

Kein Manifestwert liefert oder überschreibt die Ableitung; das Manifestfeld
`product_guard.block_base_commit` wird ausschließlich gegen die Ableitung
validiert (`of-guard-base`).

## §3 Aktuelle Kalender-Baseline

`docs/personal-jarvis/calendar-implementation-baseline-2026-08-04.md` —
unverändert gültig, mit vollständig neu gefasstem § 6 als **einziger**
normativer Stelle für Linien, Merge-Base, Kollisionsbefund und
Umnummerierungs-Mapping. Die Implementierungsbasis nach § 7 bleibt `7986bee`.

## §4 Entscheidungs-IDs nach der Auflösung

Die Kontakte-/Kalenderlinie führt `DEC-051` bis `DEC-055` sowie `ADR-0025`
und `ADR-0026`. Die IDs der Linie `jarvis/rebuild-v1` sind unverändert. Es
gibt **null** offene Doppelvergaben; die Alt-/Neu-Tabelle in Baseline § 6 ist
historischer Auflösungsnachweis.

## §5 K1-Gates — genau drei Kategorien

Quelle: `docs/personal-jarvis/modules/calendar.md` § 7 (Prüfstand) und § 8
(Offen). Jedes Gate steht in **genau einer** Kategorie. Offene Gates und
gegen Baseline akzeptierte Gates werden nicht vermischt.

### §5.1 Erfüllt (mit Evidenzreferenz)

| K1-Gate | Evidenzreferenz |
|---|---|
| Python-Testlauf `tests/personal` | `modules/calendar.md` § 7 — 1185 grün, 85 übersprungen, 1 rot (siehe § 5.3) |
| Kalender-Suite (Sync-Vertrag 27, Grenzen 23) | `modules/calendar.md` § 7 — 50 grün |
| Frontend `vitest run` | `modules/calendar.md` § 7 — 216 grün, davon 65 Kalender |
| `tsc --noEmit` | `modules/calendar.md` § 7 — grün |
| `ruff` auf neuem Code | `modules/calendar.md` § 7 — grün |
| Sidecar-Bau (`minos 12.3`, keine Schreibselektoren im Binary) | `modules/calendar.md` § 7 — grün |
| Kalenderfreier Handshake gegen das echte Binary | `modules/calendar.md` § 7 — `ready`, `ping`, `caps`, `shutdown` grün |
| Fail-closed ohne Berechtigung | `modules/calendar.md` § 7 — `outcome: failed`, kein Datensatz, kein Tombstone |

### §5.2 Gegen Baseline akzeptiert (mit Evidenzreferenz)

Derzeit **keines**. Die Kalender-Baseline sieht für kein K1-Gate eine
Baseline-Akzeptanz vor, und es ist keine maschinenlesbar gebundene
Baseline-Ausnahme für ein K1-Gate hinterlegt. Ein offenes Gate wird deshalb
nicht als akzeptiert umetikettiert.

### §5.3 Offen (mit konkretem Blockierungsgrund)

| K1-Gate | Blockierungsgrund |
|---|---|
| Echter Lesedurchlauf aus der gepackten App | Aus dem Terminal gestartet ist der verantwortliche Prozess das Terminal; der Beweis sagt nichts über Jarvis aus und trüge dem Terminal eine dauerhafte Kalenderberechtigung ein. Erforderlich auf **beiden** Architekturen. |
| ARM64 vollständig | Keine Zeile des Kalenderblocks gilt für Apple Silicon (`DEC-042`). „Unsigniertes Kind erbt den Zugriff" ist ein reiner Intel-Befund. |
| TCC-Persistenzmatrix | Rebuild, Versions-Bump, Verschieben und Quarantäne sind unbelegt. |
| Große Bestände | Laufzeit, Speicher und Fensterwahl bei tausenden Terminen sind ungemessen. |
| Teilnehmer im Echtbetrieb | Modell gebaut und getestet, im gemessenen Fenster gab es null Teilnehmer. |
| Apple-Paritätsvertrag P-1…P-15 | Erst teilweise erfüllt, nirgends visuell gegen die M2-Referenz verglichen; offen insbesondere P-7, P-9, P-12 und P-13. |
| Schreiben | Eigener Auftrag; erbt `ADR-0025`/`ADR-0026` unverändert. |
| Zweiter Datenpfad `gcalendar.py` | Unberührt; Ablöseplan steht in Baseline § 5. |
| Vorbestehend roter Test `test_dec_052_ist_registriert` | Prüft eine Zählung im Entscheidungsregister und schlägt auch ohne den Kalenderblock fehl. Vorbestehend, nicht durch B0a-3 verursacht; B0a-3 hat den Testnamen nur der Umnummerierung nachgezogen. |

## §6 Werkzeugstand

Die vollständige B0a-Werkzeugkette liegt jetzt auf der Kalenderlinie:
`scripts/gate.sh` mit den fünf Phasen und fünf Ergebnissen, Baseline-Engine
gegen `7986bee`, allowlistbasierte Evidenz, PII-Canaries, Guard-Basis,
Governance- und Allgemeinheitsprüfungen, PreToolUse-Hook und die Projektskills
`gate` und `handoff-report`. Es gibt **kein** zweites Gate-System.

Blockmanifeste: `b0a-1-tooling`, `b0a-2-governance`, `b0a-3-integration`,
`tooling-merge-readiness`.

## §7 Offene Eigentümerpunkte

1. **Bundle-Identifier** `de.kluender.jarvis.contacts-bridge` — unverändert,
   wert- und pfadgenau gepinnt. Offene Entscheidung und Fälligkeit stehen in
   `docs/personal-jarvis/17-deferred-decisions.md` § 4: spätestens vor
   Kontakte M2 oder vor der ersten produktiven signierten Freigabe.
2. **Integration von `jarvis/rebuild-v1`** in die Kalenderlinie ist **nicht**
   Gegenstand von B0a-3 und bleibt offen. Erst damit treffen die ADRs 0021 bis
   0024 und die kanonischen `DEC-044` bis `DEC-050` auf diesen Baum.

## §8 Was B0b nicht vorweggenommen findet

B0a-3 hat keine fachliche Entscheidung getroffen, keinen Produktcode
funktional geändert, kein Kalender-K1 begonnen, keine Kontakte-M2-Arbeit
geleistet, keinen Tag und kein Release erzeugt und keinen Push ausgeführt.

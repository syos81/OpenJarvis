# B0f Handoff — Dispositionshärtung: geschlossenes Vokabular, Blindstichprobe, Methodenbefunde

Alle Aussagen stammen aus maschinellen Gate-Ergebnissen
(`.gate-runtime/results/b0f-dispo-hardening.*.json`, gebunden als sanitierte
Schnappschüsse unter `config/gates/evidence/b0f-dispo-hardening/`), aus
Git-Daten und aus den committeten deklarativen Artefakten.

## §1 Rahmen

- Worktree mechanisch über `git rev-parse --show-toplevel`; Branch
  `spike/calendar-foundation-intel-2026-08-04`.
- Ausgangs-Commit `4b443e1b5a2552c09c50ab21f5f013ca37dbdbdd` (lokal == remote,
  Baum sauber); aktiver Guard 1.3.0 mit Paketdigest und Quellcommit
  `5fe885a…` mechanisch verifiziert.
- Normative Commits: Position 1 `1d0e589`, Korrekturen 2 `690d2f8`,
  3 `8afc61d`, 4 `7a0333a` — jede Korrektur maschinenlesbar im Commit-Plan
  begründet, kein Amend. Abnahmelauf vollständig gegen
  `7a0333a102285513971bb8f72bb0f0b64372e34d`.
- Delta laut `git diff --stat`: 29 Dateien, +9035/−87.

## §2 Phasen (Enum-Werte aus den maschinellen Berichten)

| Phase | Ergebnis |
|---|---|
| preflight | `pass` (13 Checks) |
| targeted | `pass` (12 Checks) |
| offline-final | `pass` (22 Checks) |
| platform-live | `not_applicable` (per Manifest, §6) |
| module-final | `pass` (4 Checks) |

## §3 B0e-Ausgangsbestand und Identität

Mechanisch rekonstruiert: 193 B0e-Dispositionen, davon 123 Ausschlüsse
(63 R9, 60 R10) — die Kontrollwerte exakt bestätigt. Migration: 119 auf das
geschlossene Vokabular; **4 B0e-Ausschlüsse wurden durch die
Ausführungsprobe falsifiziert** (Tests blieben ohne Injektion grün) und wie
die B0e-Marks repariert (`B0F-N1` in
`config/gates/history/b0f-corrections.json`). Endbestand am normativen
Commit: **128 kategorisierte Ausschlüsse (59 R9, 69 R10)** — inklusive der
Selbstanwendungs-Ausschlüsse des B0f-Werkzeugs selbst; Identität
`erkannte == kategorisierte` je Regel erzwungen (`of-b0f-baseline`,
`of-dispositions`, dauerhaft `tests/tooling/gates/test_ast_dispositions.py`).

## §4 Geschlossenes Vokabular

**14 Kategorien** (8 R9, 6 R10, IDs in `tools/gates/astcat.py`), jede mit
maschinenlesbarer Behauptung, mechanischem Prüfkriterium und positiver wie
negativer Fixture (`tests/tooling/gates/test_b0f_categories.py`); keine
Catch-all-Kategorie. Drei Prüffamilien: strukturelle AST-Kriterien,
Ausführungsproben (Injektion fingerprintgebunden neutralisiert, Lauf muss
fallen; Anwendung nach R9 selbst belegt) und Löschproben (R4-gebundener
Leser muss das Dokument ohne den Schlüssel zurückweisen). Freitext ist nur
noch Anmerkung; der Schema-2-Leser weist kategorielose Ausschlüsse zurück.
Jeder Gate-Lauf bestätigt jede Kategorie am aktuellen Kandidaten neu.

## §5 Stichprobe, Blindheit, Konsequenzen

Vorab festgeschrieben in `config/governance/b0f-sample-plan.json`: Seed =
sha256(Planversion : Commit : Register-Blob), Auswahl über Schlüsselhash,
ceil(n/5) je Regelstratum, Blind-Allowlist mit mechanischem Leck-Screen,
Digest-Bindung der Bewertungen vor dem Unblinding.

Drei Runden (nach jeder normativen Korrektur vollständig neu gezogen), je
26 gezogen == 26 bewertet, Blindheit mechanisch validiert:

| Runde | Commit | confirm | reject | insufficient |
|---|---|---|---|---|
| 1 | `690d2f8` | 20 | 6 | 0 |
| 2 | `8afc61d` | 19 | 4 | 3 |
| 3 | `7a0333a` | 23 | 1 | 2 |

Konsequenz: **kategorieweite Neubewertung über alle 14 Kategorien**
(`config/gates/history/b0f-category-rereview.json`, 128 Kandidaten, je
Ausgang und Grund). Echte Funde der Kette:

- `RC-027`: `adr_entries` normalisierte unlesbare Primärquellen zu `""` —
  zwei unlesbare Seiten verglichen sich gleich und konnten eine
  Titelkollision symmetrisch maskieren; repariert auf das bestehende
  None-Protokoll.
- `RC-028`: eine Löschprobe hielt gegen den falschen Schlüssel (Top-Level
  statt entry-lokal); der Generality-Scope-Leser validiert jetzt die
  Entry-Form als Callable-Loader.
- `RC-029`/`RC-030`: drei Vakuitätspfade im B0f-Werkzeug selbst (Rereview-
  Deckung aus unvertrauten Angaben, nutzungsleere Konsumentenzitate,
  ungescannte Comprehension-Rümpfe) — von der eigenen Neubewertung gefunden
  und geschlossen.
- `RC-031`: eine in B0e als `repair` registrierte, aber **nie
  implementierte** Reparatur (`check_anchors`: Absenz der
  Gate-Verankerungsdeklaration las sich als leere Menge) — von der
  Blindkette aufgedeckt, jetzt implementiert (`B0F-N5`).

Die verbleibende Runde-3-Ablehnung und alle insufficient-Verdikte liegen in
vollständig neubewerteten Kategorien; die Verdikte stehen unverändert in
den gespeicherten Bewertungen, nichts wurde umgewertet
(`insufficient_evidence_resolution` im Rereview-Record). Keine Ziel- oder
Bestätigungsquote.

## §6 platform-live — Herleitung

`git diff --name-only 4b443e1b..7a0333a -- tools/guard tools/guardpkg
tools/guardops src` ist leer (im Abnahmerecord gebunden); kein
Guard-Kandidat, keine Live-Pflicht, und der Slack-Nachweis läuft mit
vollständig gesperrten Sockets — kein Connector-Test wird künstlich zum
Live-Test. `pf-guard-base` prüft die aktive Installation weiterhin in jedem
Lauf.

## §7 Methodenbefunde

- **Einheitenlokalität: `open_gap`**
  (`config/governance/b0f-unit-locality.json`): Einheit und Analysegrenzen
  mechanisch hergeleitet; der Minimalfall ist reproduzierbar
  (`tests/tooling/gates/test_b0f_method.py`: Helferform 0 Kandidaten,
  Inlineform 1) bei nachweislich > 0 verbindenden Aufrufkanten. Keine
  anderweitige Abdeckung, keine bestehende normative Ausgrenzung, keine
  eigenmächtige Eigentümerentscheidung — der Befund bleibt echter
  Folgeblocker für eine spätere Methodenentscheidung.
- **Slack-Connector: kein Defekt**, mechanisch belegt
  (`tests/server/test_connectors_network_isolation.py`): die
  xoxb-Ablehnung ist eine lokale Formprüfung vor jedem Netzwerkaufruf und
  hält unter Socket-Sperre; die Gegenprobe zeigt, dass die Sperre auf dem
  xoxp-Pfad tatsächlich beißt (R9-Wirkungsnachweis der Sperre selbst).
  Kein Patch, den ein Reload verwerfen könnte; Handoff-Verweis eindeutig
  aufgelöst (`pf-/of-b0f-baseline`).

## §8 Verstoßmengenvergleich

Tooling-Suite vor dem Block 828 Tests, im Abnahmelauf 841 — kein zuvor
gefangener Verstoß entfiel, 13 Fälle kamen hinzu (RC-027 bis RC-031 samt
Gegentests). `of-violation-corpus`, `of-manifest-validation`,
`of-rule-changes` `pass`; die B0e-Negativfälle laufen unverändert.
Merkmale: 229/229 vom Vorgänger B0e zugeordnet, 0 fehlend; eigene
`B0F-`-Merkmale 18/18 verifiziert.

## §9 Protokollierte Zusatzbefunde (nicht Teil von B0f)

1. `mode_observed_wiring` (`tools/gates/runners/b0d_checks.py:392-394`)
   prüft den No-op-Pfad mit leerer Beobachtungsliste; `written == 0` kann
   „Verzeichnis fehlt" nicht von „nichts aufzuzeichnen" unterscheiden. Ein
   nichtleerer Beobachtungsfall würde die Aussage schärfen.
2. Die Blindmethode hat eine dokumentierte Erkenntnisgrenze: Ausschlüsse,
   deren Träger eine repositoryweite Probe ist, sind aus dem Blindmaterial
   allein nicht bestätigbar; das erzeugt strukturell reject/insufficient-
   Verdikte, die nur der Neubewertungspfad auflöst. Eine spätere
   Regelkodifizierung sollte diese Grenze ausdrücklich fassen.

## §10 Bestätigungen

Kein Produktcode geändert (`src/` unberührt, §6-Diff), kein Live-Lauf, kein
echter Netzwerkzugriff als Testmittel, kein Merge, kein Rebase, kein Tag,
kein Release, kein Push, keine neue Regelnummer, keine DEC-/ADR-Vergabe,
kein Folgeblock begonnen. B0f belegt die Methode; eine Regelkodifizierung
wäre Folge dieses belegten Abschlusszustands und ist nicht Teil des Blocks.

Pushstatus: `not_performed_owner_action`.

## §11 Verbleibende echte Blocker

Die Einheitenlokalität bleibt als `open_gap` ein Folgeblocker für eine
spätere Methodenentscheidung (§7); für die übrigen B0f-Ziele ist er nicht
blockierend. Der Eigentümer-Push steht aus und ist Eigentümerhandlung.

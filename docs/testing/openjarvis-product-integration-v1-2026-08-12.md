# OpenJarvis Produktintegration v1, 2026-08-12

Dieser Block baut keine Funktion. Er beendet die Branch-Zersplitterung und
erzeugt genau eine gemeinsame Basis für die weitere Produktentwicklung.

Branch: `integration/openjarvis-product-v1-2026-08-12`
Worktree: `~/Jarvis-Next-Integration`
Basis: `5bb3061bcfec5c33294aef5dcd5d21a173b08c81` (Intel Write-Helper Revalidation, PASS)
Zweiter Elternteil: `b9675dbf826a47b925ad07e1e65cb19d92c2c6ef` (Contacts arm64 Native Closure)

## 1. Die Topologie war nicht die angenommene

Mechanisch geprüft (`git merge-base --is-ancestor` über alle Paare):

```
fed4e0f7  Command Bar
   ⊂ 22d3eac4  Intel Read
      ⊂ 22887d22  Intel Write
         ⊂ 5bb3061b  Intel Write-Helper Revalidation
```

Eine lineare Kette. Nur die M2-Linie divergiert. Es gab **zwei** Linien, nicht
fünf Geschwister. Für Command Bar, Intel Read und Intel Write entsteht deshalb
kein eigener Merge — ihr Produktinhalt ist bereits vollständig Vorfahr.

Gemeinsame Basis beider Linien: `d50318d9`. Einzigartige Commits: 7 auf der
Intel-Seite, 12 auf der M2-Seite.

## 2. Klassifikation der M2-Differenz

| Kategorie | Anzahl | Inhalt |
|---|---|---|
| B — Contacts-UI / Apple-Design | 13 Dateien | `frontend/src/personal/contacts/**` inkl. `tokens.css`, neue `list/KontextMenue.tsx` |
| C — bereits patchidentisch vorhanden | 6 Dateien | Helfer-Entitlements, Reseal-Skript, drei entblindete Testdateien, Backup-Werkzeug |
| E — arm64-Evidenz und Doku | 2 Dateien | `docs/testing/contacts-arm64-native-closure-2026-08-12.md`, Gate-Tabelle |
| F — maschinenlokales Artefakt | 1 Datei | `frontend/tsconfig.tsbuildinfo` |

Kategorien A, D und G sind leer: die M2-Linie trägt keinen gemeinsamen
Produktcode ausserhalb der Oberfläche, keine arm64-spezifische Bauunterstützung
und nichts Superseded.

**Zu C.** Die sechs Dateien sind an beiden Spitzen **blobidentisch**.
`git cherry` meldet sie als verschieden, weil der Intel-Cherry-Pick den
`tsbuildinfo`-Hunk verwarf und aus `18036803` nur die Testdatei nahm. Auf
Commit-Ebene ist das korrekt, als Aussage über den Produktstand irreführend —
massgeblich ist der Endbaum. Keiner dieser Fixes wurde ein zweites Mal
eingespielt oder semantisch nachgebaut.

## 3. Methode und Konflikt

Normaler Merge (`--no-ff`), da die beiden Produktmengen disjunkt sind: 18
Dateien ausschliesslich Intel (`frontend/src/core/**` und Shell), 15
ausschliesslich M2.

Einziger Konflikt: `frontend/tsconfig.tsbuildinfo`. Der tsc-Inkrementalcache
beider Seiten beschreibt einen Quellbaum, den es nach dem Merge nicht mehr
gibt; keine der beiden Fassungen ist richtig. Aufgelöst durch **Neuerzeugung**
aus dem vereinigten Baum, nicht durch Übernahme einer Seite.

Kein Konflikt der Klassen B (Write/Security), C (Test) oder D (Doku) trat auf.
Keine Prüfung wurde geschwächt, übersprungen oder gelöscht.

## 4. Write-Relevanz: der Grund, warum keine Mutation nötig war

Diff der write-, provider- und approval-relevanten Pfade
(`src/personaljarvis/**`, `frontend/src-tauri/src/**`, `objc/**`, Entitlements,
Reseal-Skript, `tauri.conf.json`, `native/**`, `personal/contacts/api.ts`,
`data/executionTransport.ts`, `data/source.ts`):

| Vergleich | Geänderte Dateien |
|---|---|
| `5bb3061b` → Integrationsstand | **0** |
| `b9675dbf` → Integrationsstand | **0** |

Die einzige Änderung an write-*angrenzender* Oberfläche ist viermal ein
entferntes `cursor: 'default'` in `status/ContactsStatusSurface.tsx` — reine
Darstellung, keine Ausführungs-, Freigabe-, Claim- oder Settle-Semantik.

Neu hinzu kommen 13 Command-Bar-Dateien unter `frontend/src/core/**`, die es
auf der M2-Linie nie gab. Das ist **zusätzliche** Oberfläche, keine Änderung am
bewiesenen Pfad — siehe aber den offenen Punkt G unten.

## 5. Evidenz-Übertrag

| Frühere Live-Fähigkeit | Status |
|---|---|
| Contacts x86_64 CRUD (2026-08-12) | carried forward — relevante Implementierung unverändert |
| Contacts arm64 CRUD | carried forward — relevante Implementierung unverändert |
| Write-Helper Paketierung/Signierung x86_64 | auf dem Integrationsstand **neu gemessen** (siehe §6) |
| Write-Helper Paketierung/Signierung arm64 | offen bis zur M2-Prüfung desselben Commits |
| TCC-Persistenzmatrix | carried forward, unverändert offen |
| Calendar CREATE/UPDATE Intel | carried forward — Calendar-Pfade unberührt |
| Backup-/Recovery-Weg | carried forward — `scripts/contacts-backup.py` blobidentisch |
| Zehn-Szenen-Pixelabgleich | weiterhin **nicht durchgeführt** |

Der Übertrag stützt sich ausschliesslich auf die unveränderte
Code-Artefakt-Beziehung aus §4, nicht auf eine Wiederholung der Läufe.

## 6. Intel-Build und -Test auf dem integrierten Stand

| Prüfung | Ergebnis |
|---|---|
| `tsc -b` | sauber |
| Frontend (`vitest`) | 15 Dateien, **361 passed** — Command-Bar- und Contacts-UI-Tests im selben Baum |
| `tests/core` | **233 passed** |
| `tests/personal` (Contacts + Calendar) | **1353 passed, 9 skipped, 1 failed** |
| Nativer Build | x86_64, Bundle erzeugt |

Die 9 Skips sind ausnahmslos arm64- und Cross-Build-Zeilen — andere
Architektur, hier nicht ausführbar. Der Fehlschlag ist
`test_dec_052_ist_registriert`; er liest ausschliesslich
`docs/personal-jarvis/decisions-register.md`, das weder von der Intel- noch von
der M2-Seite berührt wird. Vorbestehend, nicht durch die Integration verursacht.

**Finales Intel-Paket.**

| Artefakt | Architektur | Identifier |
|---|---|---|
| `openjarvis-desktop` | x86_64 | `de.kluender.jarvis` |
| `contacts-write-helper` | x86_64 | `de.kluender.jarvis.contacts-write-helper` |
| `jarvis-contacts` | x86_64 | `de.kluender.jarvis.contacts-bridge` |
| `jarvis-calendar` | x86_64 | `de.kluender.jarvis.calendar-bridge` |

Helfer-Entitlements: **genau eins**,
`com.apple.security.personal-information.addressbook`. JIT, unsigned executable
memory, disabled library validation, beide Netzrechte, Calendar und Sandbox
sind abwesend. Alle vier DR nennen dasselbe Blatt
`34a4521ba80e5c701bf097897c794b6a5a716f14`. `codesign --verify --deep --strict`:
`valid on disk`, `satisfies its Designated Requirement`. Spike-Treffer: 0.

**Artefaktidentität.** `tauri build` baut den Helfer selbst neu; ein
vorgelagerter `cargo build` ist deshalb nicht das gepackte Artefakt. Nach
Nachziehen des externalBin-Slots tragen alle drei Stellen dieselbe
signaturinvariante Identität:

```
LC_UUID E4020B7F-7C6C-3FC1-A5E6-198C0F0CF533
  target/x86_64-apple-darwin/release/contacts-write-helper        996 656 B
  binaries/contacts-write-helper-x86_64-apple-darwin              996 656 B
  …/Jarvis.app/Contents/MacOS/contacts-write-helper             1 025 840 B
```

SHA-256 ist hier ungeeignet, weil Reseal die Bytes legitim verändert.

## 7. Oberflächenabnahme

Normativ steht der Sachverhalt in
[15-testing-and-quality-gates.md](../personal-jarvis/15-testing-and-quality-gates.md),
Absatz *Pixelabgleich*. Kurzform: Die Oberflächenabnahme ist **durch
Eigentümer-Sichtprüfung** bestanden; der Zehn-Szenen-Referenzabgleich wurde
**nicht durchgeführt**, Messevidenz gegen den M2 wird **nicht behauptet**, und
alle acht Tokengruppen bleiben `M2-VORLÄUFIG`, also unvermessen.

Pronomen, Klingelton, Nachrichtenton und Benutzername wurden nicht nachgebaut:
Der Feldvertrag v1 trägt sie nicht, und eine Oberfläche darf keine Eingaben
anbieten, die beim Speichern verloren gehen.

## 8. Offener Produktrest — nicht repariert, nicht umetikettiert

Keiner dieser Punkte wurde in diesem Safe-Lane-Block angefasst. Sie gehören vor
neue produktive Write-Funktionalität in einen eigenen Risk-Lane-Block.

| # | Punkt | Status |
|---|---|---|
| A | Die Freigabevorschau nennt den Zielcontainer nicht sichtbar. **Produktanforderung:** vor künftigen Writes muss der Eigentümer mindestens Zielcontainer/-typ und eindeutige Kennung sehen. | offen |
| B | Eine abgelaufene Freigabe zeigt weiterhin `granted`, bis ein Zugriff sie auswertet. | offen |
| C | `approved`, aber nicht ausgeführte Vorgänge sind in der Oberfläche nicht deutlich genug als offen und ausführbar erkennbar. | offen |
| D | Mehrere offene Vorbereitungen können nebeneinander bestehen, ohne dass das erkennbar wäre. | offen |
| E | Die Contacts-Detailroute liefert nach DELETE den Tombstone weiter mit HTTP 200. | `UNRESOLVED_API_SEMANTICS` — kein Defekt behauptet, solange der API-Vertrag nicht geprüft ist |
| F | Im Änderungssatz des UPDATE steht `"previous": null`, obwohl ein Vorwert existierte. | offen |
| G | Der Kontaktzweig der Command Bar (`frontend/src/core/writeAdapter.ts`) ruft `POST /mutations/{id}/execute` statt des bewiesenen App-Prozess-Kanals (claim → Tauri-`invoke` → settle). Live nie ausgeübt. Durch diese Integration steht die Command Bar erstmals auch auf arm64. | unbelegte Beobachtung, keine Defektbehauptung |

## 9. Ergebnis

| Aussage | Stand |
|---|---|
| `INTEGRATION SOURCE` | **PASS** — ein Branch trägt den vorgesehenen Produktstand |
| `INTEL x86_64 INTEGRATED BUILD` | **PASS** |
| `M2 arm64 INTEGRATED BUILD` | offen — verlangt denselben Commit auf dem M2 |

In diesem Block fand **keine** produktive Mutation statt: kein Contacts- und
kein Calendar-CREATE/UPDATE/DELETE. Die Schreibfreigabe wurde vor Beginn vom
Eigentümer entfernt.

Pushstatus: `not_performed_owner_action`.

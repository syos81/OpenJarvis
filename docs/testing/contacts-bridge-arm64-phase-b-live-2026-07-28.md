# Kontakte-Bridge-Spike G3a — arm64: Phase-B-Live-Lauf (2026-07-28)

**Gegenstand:** Erster vollständiger Phase-B-Lauf auf Apple Silicon. Betrifft
ausschließlich Spike-Code (ADR-0016), keinen Produktivcode.

**Quelle:** `<OFFICE-ARM64-MAC>` · **Testbenutzer:** `jarvisspike`
**Branch:** `spike/contacts-create-timeout-diagnostics-2026-07-27`
**Basis:** `17c9b87a`

---

## 1. Ergebnis

| Größe | Wert |
|---|---|
| Bestandene Gates | **28** |
| Fehlgeschlagene Gates | **0** |
| Nicht durchführbare Gates | **1** (G11 Mehrcontainer) |
| Gesamtstatus | **`passed_with_not_executable_gate`** |
| Mutationsausgang | durchgehend bekannt — kein `outcome_unknown` |
| Bereinigung | vollständig: laufeigene Reste **0**, Fehlschläge **0** |
| Fremdkontakte berührt | **0** — die Me-Karte des Testbenutzers blieb unverändert |
| Vorbestehende Testdatensätze berührt | **0** |

Damit sind die Spike-Ziele (b) Signierung/Packaging, (c) Change-History-Delta
und der CRUD-/Feldabdeckungsteil auf arm64 **live belegt**. Ziel (d) — Schreiben
vereinheitlichter Kontakte — konnte in dieser Umgebung **nicht geprüft** werden
und bleibt offen.

## 2. G11 ist nicht durchführbar, nicht fehlgeschlagen

Der Mehrcontainer-Test verlangt mindestens zwei Container. Das Testkonto hat
genau einen (`containerCount: 1`, belegt in `results/isolation-probe.json`).
Ein Container lässt sich nicht ohne einen zusätzlichen Account erzeugen — der
Testbenutzer hat bewusst weder Apple-ID noch iCloud.

Der frühere Code wertete das als **FAIL**. Das war eine Fehlaussage: geprüft
wurde nichts, also kann nichts fehlgeschlagen sein. `phase_b.py` kennt dafür
jetzt `not_executable()`; solche Gates zählen getrennt (`notExecutableGates`)
und führen **nicht** zu einem Fehler-Exitcode.

**Folge für den Spike:** Ziel (d) ist auf dieser Umgebung offen und muss auf
einer Installation mit zwei Containern nachgeholt werden.

## 3. Externe Änderung im Delta erkannt (LIVE-DELTA-1)

Eine **manuell in Kontakte.app** ausgelöste Änderung erschien im Change-History-
Drain. Das ist der Live-Beleg dafür, dass fremd verursachte Mutationen im Delta
ankommen und nicht durch die Echo-Unterdrückung
(`excludedTransactionAuthors`) verloren gehen.

## 4. Der Abbruch am Ende: ein Reporting-Fehler, kein fachlicher

Nach der vollständigen Auswertung brach der Lauf mit `PermissionError` ab. Der
Grund war ein Fehler im Berichtspfad, nicht in der Sache:

```
out = Path("/Users/Shared/JarvisContactsSpike/phase-b-results.json")
```

Der Pfad war fest verdrahtet und zeigte in die **Paketwurzel**, an der bereits
vorhandenen zentralen Results-Logik (`results_dir()`,
`JARVIS_CONTACTS_SPIKE_RESULTS_DIR`) vorbei. Die Paketwurzel gehört dem
Hauptbenutzer; `jarvisspike` darf dort nicht schreiben. Der Fehler war also
korrekt — falsch war das Ziel.

Zwei Mängel dahinter:

1. **Zweite parallele Wahrheit.** Die Fehlerdatei
   (`phase-b-outcome-unknown.json`) ging über `results_dir()`, die Ergebnisdatei
   nicht. Zwei Ergebnispfade im selben Skript.
2. **Vermischte Ergebnisarten.** Ein Schreibfehler am Ende hätte einen
   fachlich fehlerfreien Lauf über den Exitcode als fehlgeschlagen dargestellt.

## 5. Korrekturen in `phase_b.py`

| Bereich | Vorher | Jetzt |
|---|---|---|
| Ergebnispfad | fest verdrahtete Paketwurzel | ausschließlich `results_dir()` — eine Quelle |
| Schreibvorgang | `write_text` | temporäre Datei im Zielverzeichnis → `fsync` → `os.replace` |
| Kodierung | Standard | explizit UTF-8, abschließender Zeilenumbruch |
| Teildateien | möglich | ausgeschlossen; die temporäre Datei wird bei jedem Abbruch entfernt |
| Ergebnisinhalt | nur `name`/`pass`/`detail` | gehärtetes Modell, siehe unten |
| Detailtexte | roh | redigiert (UUID, E-Mail, Telefon, Testpräfix, Token → Platzhalter) |
| G11 ohne zweiten Container | FAIL | `not_executable` |
| Exitstatus | 0 oder 1 | 0 / 1 / 4 / 5 / 7 / **8** (siehe §7) |

## 6. Gehärtetes Ergebnismodell

Pflichtfelder: `schemaVersion`, `platform`, `architecture`, `startedAt`,
`completedAt`, `authorizationStatus`, `containerCount`, `allowExisting`,
`totalGates`, `passedGates`, `failedGates`, `skippedGates`,
`notExecutableGates`, `cleanupAttempted`, `cleanupSucceeded`,
`createdInRunCount`, `foreignContactsTouched`,
`preexistingTestContactsTouched`, `mutationsOutcomeKnown`, `reportingStatus`,
`overallStatus`.

`overallStatus` ergibt sich ausschließlich aus der Sache:

- `failedGates > 0` → `failed`
- sonst `notExecutableGates > 0` → `passed_with_not_executable_gate`
- sonst → `passed`

`reportingStatus` ist davon **getrennt** (`written`, `write_failed`,
`reconstructed_after_path_error`). Ein Schreibfehler verändert weder
`overallStatus` noch die Gate-Zählung.

`foreignContactsTouched` und `preexistingTestContactsTouched` sind konstruktiv
**0**: Mutationen laufen ausschließlich gegen `CREATED_IN_RUN`, geprüft durch
`assert_run_owned()` und zusätzlich durch die Sidecar-Rail.

## 7. Getrennte Exitstatus

| Code | Bedeutung |
|---|---|
| `0` | alle ausführbaren Gates bestanden — nicht durchführbare Gates sind **kein** Fehler |
| `1` | mindestens ein fachliches Gate fehlgeschlagen |
| `4` | Autorisierung noch nicht entschieden |
| `5` | Autorisierung verweigert bzw. gesperrter Aufruf (`--cleanup-only`) |
| `7` | Mutationsabbruch mit unbekanntem Ausgang |
| `8` | Tests vollständig gelaufen, **nur** das Schreiben schlug fehl |

Ein fachlicher Fehler hat Vorrang vor einem Reporting-Fehler: `1` schlägt `8`.

## 8. Rekonstruktion der Ergebnisdatei

`results/phase-b-results.json` wurde **administrativ** nachgeschrieben
(`scratch/contacts-spike/reconstruct_results.py`). Der Live-Lauf wurde
**nicht wiederholt**:

- `reconstructed: true`
- `reconstructionReason: "final-report-path-permission-error"`
- `liveRunRepeated: false`

Es wurde dabei **kein** Kontakt gelesen, angelegt, geändert oder gelöscht,
**kein** Sidecar gestartet und **kein** `requestAuthorization` gesendet.

Jeder Wert trägt in `provenance` seine Herkunft. Nicht Belegbares steht als
`null` und wird nicht geschätzt — insbesondere `startedAt` und `completedAt`,
weil die Konsolenausgabe keine Zeitstempel enthielt. Die **Einzelheiten je
Gate** gingen mit der fehlgeschlagenen Schreiboperation verloren; `gates` bleibt
deshalb leer und `gateDetailsAvailable` steht auf `false`. Sie werden **nicht**
rekonstruiert.

`createdInRunCount: 2` ist aus dem tatsächlich ausgeführten Pfad abgeleitet
(`G8-stufe1-create`, `G10-create`); die beiden G11-Creates wurden wegen des
nicht durchführbaren Gates nie erreicht.

## 9. Tests

Neu: `scratch/contacts-spike/test_phase_b_reporting.py` — **32** kontaktfreie
Prüfungen zu Ergebnispfad, Atomarität, fehlendem und gesperrtem
Zielverzeichnis, Trennung von Reporting- und Sachurteil, Exitcodes,
Gate-Zählung 28+1, PII-Freiheit der Datei und Rekonstruktionsfeldern.

Gesamtstand kontaktfreier Prüfungen: **187**

| Suite | Prüfungen |
|---|---|
| `driver.py --protocol-test` | 25 |
| `test_driver_failmodes.py` | 26 |
| `test_authorization_profiles.py` | 37 |
| `test_enumerate_diagnostics.py` | 38 |
| `test_isolation_probe.py` | 29 |
| `test_phase_b_reporting.py` | 32 |

Alle grün. Keine dieser Prüfungen startet einen Sidecar gegen den Store, löst
einen TCC-Dialog aus oder berührt einen Kontakt.

## 10. Offen

- **Ziel (d)** — Schreiben vereinheitlichter Kontakte: auf dieser Umgebung
  mangels zweitem Container nicht prüfbar.
- **Einzelheiten je Gate** des Live-Laufs: unwiederbringlich verloren; die
  Bilanz (28/0/1) ist belegt, die Einzelbegründungen sind es nicht.
- **Zeitstempel** des Laufs: nicht belegbar.
- **Intel-x86_64-Abnahme**: separat, unverändert offen.

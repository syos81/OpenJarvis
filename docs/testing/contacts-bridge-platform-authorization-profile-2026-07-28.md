# Kontakte-Bridge-Spike G3a — Plattformprofil für `authorize.py` (2026-07-28)

**Gegenstand:** Beseitigung des Blockers, der die native arm64-Autorisierung
verhinderte. Betrifft ausschließlich Spike-Code (ADR-0016), keinen Produktivcode.

**Quelle:** `<OFFICE-ARM64-MAC>`
**Branch:** `spike/contacts-create-timeout-diagnostics-2026-07-27`
**Basis:** `eb3b12e683cb068a006ae8dcf44c0d56c3c00f36`

---

## 1. Ursache des Blockers

`authorize.py` ist der einzige vorgesehene Weg, den ersten TCC-Kontakte-Dialog
auszulösen (eine normale Store-Operation scheitert bei `notDetermined` vorher am
`requireAuth`-Gate des Sidecars mit `tcc_denied`).

In der Fassung aus dem Diagnose-Commit waren zwei plattformspezifische Werte
**fest im Python-Code verdrahtet**:

```python
EXPECTED_DR   = 'identifier "de.jarvis.contacts-spike.sidecar" '
                'and certificate leaf = H"f378c267…"'    # Intel-Zertifikat
EXPECTED_ARCH = "x86_64"                                  # Intel-Architektur
```

Beide waren weder per Argument noch per Umgebungsvariable überschreibbar und
wurden fail-closed geprüft. Auf einem Apple-Silicon-Gerät mit eigenem
Spike-Zertifikat brach `authorize.py` daher **vor dem Start des Sidecars** ab —
sicher, aber die arm64-Abnahme war blockiert.

## 2. Neues Modell: lokales Plattformprofil

Architektur und Zertifikats-Leaf stehen nicht mehr im Code, sondern in einem
lokalen, schreibgeschützten Profil des Übergabepakets:

```
<HANDOFF>/tools/authorization-profile.json
```

Es wird bei der **administrativen Paketbereitstellung** aus bereits unabhängig
geprüften Build- und Signaturwerten erzeugt. Der Testbenutzer darf es nur lesen.

### Warum die Werte nicht aus dem Sidecar übernommen werden

Ein Ableiten der Erwartungswerte aus der zu prüfenden Binärdatei wäre eine
**zirkuläre Identitätsprüfung**: Jede manipulierte oder fremd signierte Datei
würde ihre eigenen Werte mitbringen und sich damit selbst bestätigen. Das Profil
ist deshalb eine **unabhängige, vorab festgelegte Referenz**; der Sidecar wird
gegen sie geprüft, nie umgekehrt.

Der SHA-256 des Sidecars wird bewusst **nicht** im Profil dupliziert — dafür
bleibt der eindeutige Eintrag in `SHA256SUMS.txt` die einzige Quelle.

## 3. Gleichwertigkeit arm64 / x86_64

Der Python-Code ist auf beiden Plattformen **identisch**. Nur das Profil
unterscheidet sich:

| | Büro (Apple Silicon) | Privates MacBook (Intel) |
|---|---|---|
| `architecture` | `arm64` | `x86_64` |
| `certificateLeafSha1` | `0139fb6e…` | `f378c267…` |

Im Code gibt es **keine Geräteliste und keinen Fingerprint**. `uname` wird nicht
zur Auswahl verwendet, sondern ausschließlich **gegen den Profilwert verifiziert**
— ein Paket auf dem falschen Gerät bricht ab.

## 4. Fail-closed-Prüfungen

**Am Profil selbst, vor jedem Sidecar-Start:** fester Pfad · reguläre Datei ·
kein Symlink (Datei und jedes Pfadelement im Paket) · gehört nicht dem
Testbenutzer · nicht beschreibbar für Testbenutzer, Gruppe und andere (POSIX-Bits
**und** ACL) · genau ein `SHA256SUMS`-Eintrag · Hash stimmt · exakt die
Pflichtfelder, keine unbekannten Felder · `schemaVersion == 1` ·
`platform == macOS` · `architecture ∈ {arm64, x86_64}` · Host-Architektur
stimmt mit Profil überein · `minimumSystemVersion == 12.3` ·
`sidecarRelativePath` weder absolut noch mit `..`, exakt `tools/jarvis-contacts` ·
`certificateLeafSha1` exakt 40 Hex-Zeichen · **`designatedRequirement` wird aus
den Profilwerten rekonstruiert und muss wortgleich sein**.

**Am Sidecar, gegen das Profil:** regulär und kein Symlink · SHA-256 laut
Manifest · `codesign --verify --strict` · DR wortgleich · Leaf in der DR
enthalten · Authority laut Profil · Hardened Runtime · keine Ad-hoc-Signatur ·
Entitlements leer · `CFBundleIdentifier` und `NSContactsUsageDescription` exakt ·
Architektur exakt · kein Universal-Binary · `minos` exakt.

Jede Abweichung: technische Fehlermeldung, **kein** Sidecar-Start, **kein**
`requestAuthorization`, Exitcode ungleich 0.

## 5. TOCTOU-Schutz

Nach dem Start des Sidecars und **vor** jeder Anforderung werden erneut geprüft:
Pfad, Symlink-Status, Dateityp sowie **Sidecar- und Profil-SHA-256**. Weicht
etwas ab, wird der Child sofort beendet und fail-closed abgebrochen. Der
Profil-Hash im Recheck ist neu — die vorherige Fassung prüfte nur den Sidecar.

## 6. Kontaktfreie Testergebnisse

| Suite | Ergebnis |
|---|---|
| `test_authorization_profiles.py` (neu) | **37/37** |
| `test_driver_failmodes.py` | **24/24** |
| Protokolltests (Worktree-Build) | **25/25** |
| Protokolltests (Paket-Sidecar) | **25/25** |

Die Profil-Suite arbeitet ausschließlich mit temporären Kopien und
Mock-Kommandoausgaben (`codesign`, `otool`, `lipo`). Sie deckt alle 27
geforderten Fälle ab, darunter: gültige arm64- und x86_64-Profile, fehlendes /
verlinktes / beschreibbares Profil, fehlender / doppelter / falscher Hash,
Schema-, Plattform-, Architektur-, Host-Mismatch-, Versions-, Pfad-, Leaf- und
DR-Verstöße, abweichende Sidecar-DR/Authority/Architektur/Usage/Identifier,
Ad-hoc-Signatur, vorhandene Entitlements, Universal-Binary sowie beide
TOCTOU-Fälle. Test 27 belegt mit einem Spy, dass die Vorprüfung **keinen**
Sidecar startet. Zwei Zusatzprüfungen belegen, dass im Quelltext **weder** eine
Architektur-Konstante **noch** ein Zertifikats-Fingerprint steht.

**In keinem Test wurde `requestAuthorization` gesendet, ein TCC-Dialog
ausgelöst, eine Store-Operation ausgeführt oder ein Kontakt berührt.**
`authorizationStatus` blieb durchgehend `notDetermined`.

## 7. Stand

`authorize.py` wurde **nicht ausgeführt**. Die Autorisierung auf dem
Büro-arm64-Gerät steht weiterhin aus und erfolgt erst nach ausdrücklicher
Freigabe im Testbenutzer `jarvisspike`.

Keine privaten Schlüssel, keine TCC-Daten und keine Kontaktdaten sind Teil
dieser Änderung.

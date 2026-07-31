# Kontakte — x86_64-Abnahme des produktiven Lese- und Sync-Pfads (2026-07-31)

**Gegenstand:** Produktive Live-Abnahme des Kontakte-Moduls auf Intel:
Wiederherstellung der am 2026-07-30 irrtümlich lokal gelöschten Spiegelkontakte,
anschliessender Vollabgleich, Delta-Läufe und Cursorfortsetzung über einen
echten Anwendungsneustart.

**Betrifft Produktivcode** (nicht den Spike aus ADR-0016). Referenzen:
`docs/adr/ADR-0016-swift-contacts-bridge.md`,
`docs/adr/ADR-0018-dual-architecture-macos-support.md`,
`docs/personal-jarvis/modules/contacts.md`,
[`contacts-arm64-read-sync-validation-2026-07-31.md`](contacts-arm64-read-sync-validation-2026-07-31.md).

> Alle Zahlen sind aggregiert. Dieses Dokument enthält **keine** Kontaktdaten,
> keine Namen, keine Provider- oder Container-Identifier, keine Cursor oder
> Token, keine Zertifikatsangaben und keine privaten Pfade. Containerkennungen
> erscheinen ausschliesslich als maskierte Referenz (`C-…`, nicht
> zurückrechenbar).

---

## 1. Host und Codeobjekte

| Merkmal | Wert |
|---|---|
| Architektur | Intel MacBook, **x86_64** (nativ, kein Rosetta) |
| Betriebssystem | macOS 12.7.6 |
| Anwendung | produktive `Jarvis.app`, auf diesem Gerät gebaut und signiert |
| App-Identifier | `de.kluender.jarvis` |
| Sidecar-Identifier | `de.kluender.jarvis.contacts-bridge` |
| Beide Binaries | `x86_64`, Mindestversion `12.3` |
| Hardened Runtime | bei App **und** Sidecar gesetzt |
| Designated Requirement | zertifikatsgebunden bei beiden; kein `cdhash` |
| Signaturprüfung | `codesign --verify --strict --deep` erfolgreich |

**Entitlements — geprüft am gebauten Bundle:**

| | App | Sidecar |
|---|---|---|
| `personal-information.addressbook` | ja | ja |
| `app-sandbox` | `false` | nicht vorhanden |
| `inherit` | nicht vorhanden | nicht vorhanden |
| JIT, unsignierter Speicher, abgeschaltete Library-Validation | vorhanden | **nicht** vorhanden |
| Netz, Dateiauswahl | vorhanden | **nicht** vorhanden |
| **Anzahl Einträge** | 8 | **genau 1** |

Damit ist das Entitlement-Modell auf beiden Architekturen identisch belegt.

## 2. Ausgangszustand vor der Abnahme

| Grösse | Wert |
|---|---|
| aktive Kontakte | **0** |
| lokal tombstonete Spiegelkontakte | **116** |
| Tombstone-Zeilen | 116 |
| Tombstone-Grund | durchgehend `absent_in_complete_enumeration` |
| externe Identitäten | 116 |
| Sync-State-Zeilen | 2 |
| Migrationsledger | 0001 – 0004 |
| `contacts_sync_audit` | existierte nicht |
| forensische Sicherung | vorhanden, byteidentisch zur Live-Datenbank |

**Bei Apple selbst war nichts verändert.** Die Provider-Identifier waren
unversehrt; die Löschung war ausschliesslich lokal.

## 3. Migration 0005

Beim Start der Anwendung führte der Bootstrap die Migration **genau einmal**
aus.

| Grösse | vorher | nachher |
|---|---|---|
| Migrationsledger | 0001 – 0004 | **0001 – 0005** (`schema_version` 5) |
| Audit-Tabellen | keine | `contacts_sync_audit`, `contacts_sync_audit_containers` |
| aktive Kontakte | 0 | 0 |
| tombstonete Kontakte | 116 | 116 |
| Tombstone-Zeilen und -Gründe | 116 / `absent_in_complete_enumeration` | unverändert |
| Sync-State-Zeilen | 2 | 2 |
| Audit-Läufe unmittelbar danach | — | **0** |

Die Migration ist rein additiv: kein fachlicher Contacts-Bestand wurde
verändert. Es fand dabei **kein** Store-Zugriff statt — der Sidecar wurde nicht
gestartet.

## 4. Wiederherstellung

Ausdrücklich über den Recovery-Endpunkt ausgelöst, mit beiden
Pflichtbestätigungen im Körper.

| Grösse | Wert |
|---|---|
| Modus | `recovery` |
| Container | 2 |
| Enumeration je Container | `C-1b3d99`: 115 gemeldet / 115 erhalten · `C-4b8df1`: 2 / 2 |
| Vollständigkeit und Zählung | beide `complete`, beide konsistent |
| empfangene Providerkontakte | **117** |
| reaktivierte lokale Datensätze | **116** |
| neue lokale Kontakt-IDs | **0** — dieselben 116 Kennungen |
| Duplikate | **0** (116 Kontakte, 116 verschiedene IDs, 116 verschiedene Provider-Identifier) |
| Tombstone-Zeilen umgeschrieben | **116** auf `reconciled_after_suspicious_empty_enumeration` |
| harte Löschungen | **0** — der Beleg der früheren Löschung bleibt erhalten |
| aktive Tombstones danach | **0** |
| Sync-State danach | beide Container `full_diff_required`, **ohne** Cursor |
| Ausgang | `committed` |
| Dauer | 936 ms |
| veränderte Apple-Kontakte | **0** |

Der 117. Providerdatensatz wurde bewusst **nicht** importiert: die
Wiederherstellung reaktiviert nur bekannte Provider-Identifier. Ein Import
gehört in den Sync (siehe §5).

## 5. Vollabgleich nach der Wiederherstellung

| Grösse | Wert |
|---|---|
| Modus | `full_diff_account` |
| Container | 2 |
| Enumeration je Container | `C-1b3d99`: 115 / 115 (vorher 114) · `C-4b8df1`: 2 / 2 (vorher 2) |
| empfangene Kontakte | **117** |
| importiert | **1** — der zuvor unbekannte Datensatz |
| unverändert verarbeitet | **116** |
| geändert / tombstoned | 0 / **0** |
| Cursor vorher / nachher | vorhanden / vorhanden, für **beide** Container gesetzt |
| `suspicious_empty` | 0 |
| Ausgang | `committed` |

Die Null-Gegenprobe konnte hier nicht anschlagen und musste es auch nicht: sie
greift bei `previous_count > 0` **und** `received_count == 0`; beide
Enumerationen lieferten vollständige, konsistente Zahlen.

## 6. Delta- und Neustartprüfung

| Grösse | Wert |
|---|---|
| Benutzer-Syncs | 2 (einer vor, einer nach dem Neustart) |
| Delta-Läufe je Benutzer-Sync | 2 — einer je Container |
| Delta-Audit-Runs insgesamt | **4** |
| Ausgang | alle `committed` |
| Change-Ereignisse je Lauf | **0** |
| Cursor vorher / nachher | in allen vier Läufen vorhanden / vorhanden |
| Importiert, geändert, tombstoned | je 0 |
| Unerwartete Voll-Diffs | **keine** — `full_diff_required` blieb überall 0 |
| `dropEverything` | **nicht aufgetreten** |
| `suspicious_empty_enumeration` | **nicht aufgetreten** |
| Zwischen den Syncs | **echter Neustart** von Anwendung und Backend über LaunchServices |
| Cursorfortsetzung nach Neustart | erfolgreich; beide Container blieben im Modus `delta` |
| Recovery-Läufe während dieser Phase | **0** |
| Autonomer Sync | **keiner** — jeder Lauf war ausdrücklich ausgelöst |

**Ein Lauf, eine Spur.** Jeder Delta-Lauf trägt eine eigene `run_id`; ein
Benutzer-Sync über zwei Container erzeugt zwei Läufe, keine verschachtelten
Doppelläufe. Delta-Läufe schreiben erwartungsgemäss **keine**
Container-Enumerationszeilen: ein Delta zählt nicht auf.

## 7. Produktiver Intel-Endstand

| Grösse | Wert |
|---|---|
| aktive Kontakte | **117** |
| aktive Tombstones | **0** |
| externe Identitäten | 117 |
| abgeglichene Tombstone-Historien | 116 |
| Sync-State-Zeilen | 2 |
| Modus beider Container | `delta` |
| Cursor | vorhanden |
| Circuit | `closed` |
| Recovery-Audit-Läufe | **1** |
| Full-Diff-Account-Audit-Läufe | **1** |
| Delta-Audit-Läufe | **4** |
| Ausgang aller sechs Läufe | `committed` |
| Provider-Mutationen | **0** |

**Datenschutz der Spur — am Livebestand geprüft:** keine Container-Kennung im
Klartext (null Zeilen ohne `C-`-Präfix), kein Kontaktwert, kein Cursorwert. Der
Cursor erscheint ausschliesslich als Wahrheitswert.

## 8. Abweichungen während der Abnahme

Alle drei betrafen die Durchführung, nicht das Produkt. Sie werden hier
festgehalten, weil eine Abnahme, die ihre eigenen Fehltritte verschweigt,
weniger wert ist als eine, die sie benennt.

### A. Doppelter Recovery-POST

Die verwendete Shell-Zeile leitete die Antwort durch einen Formatierer mit
`||`-Rückfall. Der Formatierer scheiterte an einer angehängten Statuszeile,
woraufhin der Rückfallzweig den **nicht idempotenten** POST ein zweites Mal
sendete.

* Der **erste** POST führte die Wiederherstellung aus; seine Antwort ging in
  der fehlgeschlagenen Pipe verloren.
* Der **zweite** POST wurde fail-closed mit `already_reconciled` abgewiesen.
* **Kein** zweiter Recovery-Lauf, **keine** doppelte Reaktivierung, **kein**
  Schaden — belegt durch genau einen `recovery`-Eintrag in der Auditspur.
* Die Auditspur ermöglichte die vollständige Rekonstruktion des verlorenen
  Ergebnisses. Genau dafür wurde sie gebaut.

### B. Fehlversuch mit HTTP 000

Der erste Sync-Aufruf erreichte den Server nicht — die Anwendung war zwischen
Portprüfung und Anfrage nicht mehr erreichbar (kein Absturzbericht). Geprüft
und belegt: **kein** Audit-Lauf, **keine** Datenänderung. Danach kontrollierter
Neustart und erfolgreicher Lauf.

### C. Roh ausgegebene Container-Identifier

Während der manuellen Prüfung wurde die Antwort von `GET /sync/status` einmal
unbearbeitet im Terminal ausgegeben. Dadurch erschienen **technische
Container-Identifier** im Klartext.

* Betroffen waren ausschliesslich Containerkennungen — **keine** Namen,
  Telefonnummern, E-Mail-Adressen oder sonstigen Kontaktinhalte.
* Die interne Auditspur blieb davon unberührt und enthält weiterhin nur
  maskierte Referenzen.
* **Härtung, erledigt am 2026-07-31:** Der öffentliche `SyncStatusOut`-Vertrag
  gab `container_identifier` und `provider_account_id` roh zurück, obwohl die
  Oberfläche beide Felder nicht typisiert und nie angezeigt hat. Er gibt
  stattdessen jetzt `provider_type`, `account_ref` und `container_ref` heraus;
  die Maskierung ist dieselbe wie in der Auditspur. Siehe
  `docs/personal-jarvis/modules/contacts.md` §15.

## 9. Abnahmeaussage

**Der x86_64-Lese- und Sync-Pfad einschliesslich Wiederherstellung,
Auditierung und Neustart gilt als produktiv abgenommen.**

Zusammen mit der arm64-Abnahme vom selben Tag sind damit **beide** in ADR-0018
festgelegten Produktionsarchitekturen gleichwertig validiert: Mehrcontainer,
Vollabgleich, Delta, Neustart, Cursorfortsetzung und Auditspur sind auf jeder
von beiden auf echter Hardware belegt.

Ein künstlich herbeigeführter Provider-`DELETE`-Livetest ist auch hier **nicht**
Voraussetzung: der Pfad ist automatisiert abgedeckt, und ein Livetest verlangte
eine Mutation an echten Kontaktdaten.

## 10. Zum Vorfall vom 2026-07-30 — Stand der Ursachenklärung

Was **belegt** ist: Eine Enumeration meldete null Datensätze bei gesetztem
Vollständigkeitsmarker, und der damalige Code leitete daraus eine Löschmenge
ab. Der Schutz dagegen — kontoweite Löschbasis, einmalige Null-Gegenprobe,
`suspicious_empty` — ist implementiert, getestet und auf beiden Architekturen
im Einsatz. Die lokalen Folgen sind mit dieser Abnahme vollständig behoben.

Was **Hypothese bleibt**: warum der Provider in diesem Moment null Datensätze
meldete. Ein `dropEverything` in Verbindung mit einem vorübergehend leer
erscheinenden Store ist plausibel, aber **nicht belegt** — weder durch
Apple-Dokumentation noch durch eine Reproduktion. Der Zustand liess sich unter
identischen Bedingungen nicht wieder herbeiführen. Er wird ausdrücklich als
offene Hypothese geführt und **nicht** als Ursache behauptet.

## 11. Weiterhin offen

Siehe `docs/personal-jarvis/modules/contacts.md` §15.

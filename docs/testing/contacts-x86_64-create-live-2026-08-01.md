# CREATE-X86_64-LIVE NICHT BESTANDEN (2026-08-01)

**Gegenstand:** erster produktiver Apple-Contacts-Schreibversuch von Personal
Jarvis — Phase M2 aus [ADR-0019](../adr/ADR-0019-provider-mutation-architecture.md).

**Gerät:** Intel x86_64, macOS 12.7.6 (21H1320) · **Branch:**
`handoff/contacts-read-flow-2026-07-29` · **Stand:** `e85cb78`

---

## 1. Ergebnis

**Der funktionale Create-Pfad ist nicht bestanden.** Der Sidecar starb während
der Übergabe an Apples Speicherpfad; es entstand kein Kontakt.

**Alle Sicherungen sind bestanden.** Genau ein Sendversuch, korrekte
Einstufung als ungewisser Ausgang, kein automatischer Wiederholungsversuch,
keine Veränderung an bestehenden Daten.

Beides gehört zusammen: der Vorgang hat sein Ziel verfehlt, aber er hat auf
dem Weg dorthin nichts kaputtgemacht — und das war die eigentliche Frage
dieses ersten Livetests.

| Aussage | Stand |
|---|---|
| Funktionaler Create-Pfad | **nicht bestanden** |
| Provider-Sendversuche | **genau 1** |
| Abbruchart | Sidecar-SIGABRT **in Apples Speicherpfad** |
| Kontakt nach manueller Sichtprüfung | **nicht vorhanden** |
| Bestehende Kontakte verändert | **nein** — 117 vorher, 117 nachher, 0 Tombstones |
| At-most-once-Sperre | **bestanden** |
| Freigabebindung | **bestanden** |
| Retry-Sperre | **bestanden** |
| Ursache | **nicht bewiesen** |

## 2. Ablauf

| Schritt | Ergebnis |
|---|---|
| Start der gepackten App | Migration `0006` live angewandt, Bestand unverändert |
| `GET /capabilities` | `create_supported: true`, `update`/`delete`: `false` |
| Vorbereiten | `awaiting_approval`, vollständige Vorschau, Containerreferenz maskiert; **kein Send** |
| Freigeben | `granted` durch einen Menschen; **kein Send** |
| **Ausführen** | nach 0,97 s: `outcome_unknown`, `child_signalled`, `retryable: false` |
| Zweiter Ausführungsversuch | **HTTP 409**, kein zweiter Sidecar-Start |
| Manuelle Sichtprüfung in Apple Kontakte | Testkontakt **nicht vorhanden** |

Vor- und Nachzustand sind unter `~/.jarvis-forensics/` gesichert (0700/0600).

## 3. Zustand der fehlgeschlagenen Mutation

| Feld | Wert |
|---|---|
| `state` | `outcome_unknown` |
| `outcome` | `outcome_unknown` |
| `last_error_code` | `child_signalled` |
| Outbox | `outcome_unknown`, `attempt_count = 1`, Claim freigegeben |
| Freigabe | `R1`, `consumed`, menschlich entschieden |
| Providerziel / Read-back-Beleg / lokales Ziel | jeweils **nicht gesetzt** |
| Auditkette | 7 Stufen, lückenlos bis `outcome_unknown` |

Der Zustand bleibt unverändert stehen. Er ist die korrekte Aussage des
Systems: **zum Zeitpunkt der Entscheidung war der Ausgang nicht beweisbar.**
Die spätere Sichtprüfung ist eine menschliche Beobachtung — sie ändert nichts
daran, was das System wissen konnte, und wird deshalb nicht rückwirkend als
Systemwissen ausgegeben.

## 4. Belegte Ursache

Aus dem Absturzbericht des Systems (PII-arm wiedergegeben):

| Angabe | Wert |
|---|---|
| Prozess | `jarvis-contacts`, **x86_64** |
| Betriebssystem | macOS 12.7.6 (21H1320) |
| Ausnahmetyp | `EXC_CRASH`, Signal **SIGABRT** |
| Termination Reason | im Bericht **leer** |
| Exception Reason | im Bericht **nicht enthalten** |
| Zusatzangabe | `libsystem_c.dylib: abort() called` |
| Betroffener Thread | 0 (von 7) |

Aufrufkette der geworfenen Ausnahme, von innen nach aussen:

```
CoreFoundation       __exceptionPreprocess
libobjc.A.dylib      objc_exception_throw
CoreData             -[NSPersistentStoreCoordinator executeRequest:withContext:error:]
CoreData             -[NSManagedObjectContext save:]
AddressBookCore      -[ABManagedObjectContext save:]
Contacts             -[CNCDSaveRequestExecutor executeSaveRequest:]
ContactsPersistence  -[CNCDPersistenceContext performBlockAndWaitWithManagedObjectContext:]
```

**Damit ist belegt:** Eine Objective-C-Ausnahme entstand **innerhalb von
Apples eigener Speicherlogik**, nachdem der Speicherauftrag bereits übergeben
war. Sie war nicht abgefangen, die C++-Laufzeit beendete den Prozess. Aus
Swift ist eine solche Ausnahme nicht fangbar.

**Ebenfalls belegt:** Die gesendete Nutzlast war strukturell einwandfrei. Eine
erneute Prüfung derselben gespeicherten Nutzlast gegen den Feldvertrag v1
ergibt: gültig, kanonisch unverändert, Labels aus dem geschlossenen Vorrat
(`work`, `mobile`), Zielcontainer gesetzt, kein Providerziel und keine
Revision (beides korrekt für eine Neuanlage). Die Ausnahme stammt **nicht**
aus einer Vertrags-, Feld- oder Labelverletzung.

**Ebenfalls belegt:** Der Zielcontainer existierte beim Speichern. Der Sidecar
löst ihn unmittelbar vor dem Objektaufbau über eine exakte Kennungssuche auf
und hätte sonst vor jeder Übergabe abgebrochen.

## 5. Nicht bewiesene Ursachen

Warum Apples Speicherlogik wirft, ist **offen**. Der Grundtext der Ausnahme
fehlt an beiden Stellen, an denen er hätte stehen können: der Absturzbericht
enthält weder `exceptionReason` noch eine Termination Reason, und die
`stderr`-Übernahme der Bridge hat den Ausnahmedump vollständig redigiert
(siehe §6).

Als **Hypothesen** festgehalten, keine davon belegt:

1. **Containerbezogene Besonderheit.** Geschrieben wurde in einen
   kontogebundenen Container; der Spike auf arm64 hatte erfolgreich in den
   lokalen Container geschrieben. Das ist der einzige auffällige Unterschied.
2. **Zustand des lokalen Adressbuchspeichers.** Die Ausnahme entsteht in der
   CoreData-Schicht von `AddressBookCore`, nicht in der Contacts-API darüber.
3. **Plattformspezifisches Verhalten unter macOS 12.7.6.** Ein vergleichbarer
   SIGABRT trat am 2026-07-28 auf arm64 im Lesepfad auf.

**Hypothese 1 wird ausdrücklich nicht zur Produktregel gemacht.** „CardDAV-
oder iCloud-Container sind nicht schreibbar" ist eine Behauptung über Apples
Verhalten, die dieser eine Absturz nicht trägt. Eine solche Regel würde
funktionierende Ziele dauerhaft sperren, ohne dass jemand geprüft hätte, ob
sie funktionieren.

**Für den nächsten Test gilt sie dagegen als Auswahlkriterium:** der
Testplan benennt ausdrücklich den **lokalen** Container. Das ist eine
Entscheidung über den Test, nicht über das Produkt.

## 6. Diagnoseverlust — behoben

Die `stderr`-Übernahme liess ausschliesslich eigene Diagnosezeilen der Bridge
durch. Ein Ausnahmedump beginnt mit keiner davon; er wurde vollständig durch
identische Platzhalter ersetzt. Derselbe Verlust war im arm64-SIGABRT-Bericht
vom 2026-07-28 bereits benannt und im Produktcode noch offen.

Seit diesem Stand bleiben erhalten: die **Ausnahmeklasse**, der
Laufzeit-Abbruchmarker und die **Stapelzeilen** mit Bibliotheks- und
Symbolnamen. Nicht übernommen wird der Grundtext der Ausnahme — er ist
Freitext, den das System mit beliebigen Werten füllen darf; gemeldet wird nur,
**dass** es einen gab. Keine fremde Zeile wird wörtlich übernommen; jede
Ausgabe ist aus geprüften Bestandteilen zusammengesetzt. Send-, Retry- und
Ergebnisklassifikation sind unverändert.

## 7. Fehlender manueller Abschlussweg

Nach einer externen Sichtprüfung gibt es **keinen** Weg, festzuhalten:
„Provideränderung nicht beobachtet; Vorgang ohne erneuten Send schliessen."

| Weg | Ergebnis aus `outcome_unknown` |
|---|---|
| `execute` | 409 — führt nie zurück |
| `reject` / `cancel` / `expire` | scheitert: sie verlangen eine **wartende** Freigabe, diese ist verbraucht |
| `reconcile` | verlangt einen Providerzugriff; ohne Providerkennung endet er ohnehin bei `manual_decision_required` |

Zusätzlich ist `manual_decision_required` selbst eine **Sackgasse**: der
Zustand wird gesetzt, aber von keinem Übergang verlassen.

Das ist eine Produkt- und Architekturlücke. Sie wurde zunächst **gemeldet,
nicht improvisiert** — ein neuer Zustandsübergang gehört in eine Entscheidung,
nicht in eine Fehlerbehebung.

**Geschlossen am 2026-08-01** (ADR-0019 §5a): Es gibt jetzt den terminalen
Zustand `manually_resolved_not_applied` und die Route
`POST …/mutations/{id}/resolve-outcome` mit geschlossenem Vertrag
(`not_observed` / `manual_provider_inspection`, kein Freitext). Sie berührt
den Provider nicht, ist nur aus `outcome_unknown` und
`manual_decision_required` zulässig, verlangt eine verbrauchte Freigabe und
ermöglicht niemals einen zweiten Send. Der Auditeintrag `outcome_unknown`
bleibt stehen; der Abschluss ist ein eigenes, späteres Ereignis.

**Die hier beschriebene Live-Mutation ist noch nicht aufgelöst.** Sie steht
weiterhin auf `outcome_unknown` und wartet auf eine ausdrückliche Entscheidung.

## 8. Was nicht geschah

Kein zweiter Schreibversuch. Kein Abgleich mit Providerzugriff. Kein Sync,
keine Wiederherstellung. Kein Kontakt angelegt, verändert oder gelöscht. Keine
Änderung an `jarvis/rebuild-v1`.

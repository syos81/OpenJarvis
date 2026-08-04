# Kalender-Leseprobe x86_64 — 2026-08-04

Erster Nachweis, dass sich Kalender und Termine auf diesem Gerät lesen lassen.
**Rein lesend.** Kein Termin wurde erstellt, geändert oder gelöscht; die
Probe enthält keinen Schreibaufruf, und ein Test hält das fest.

## Umgebung

| | |
|---|---|
| Architektur | x86_64 (Intel) |
| macOS | 12.7.6 (Build 21H1320) |
| Swift / SDK | 5.7.2 / MacOSX 13.1 |
| Zertifikat | „Personal Jarvis Contacts Spike" (`F378C267…`) |
| Benutzer | Hauptbenutzer (kein separater Testbenutzer — es wurde nichts geschrieben) |
| Artefakt | `spikes/calendar-foundation/build/JarvisCalendarProbe.app`, Hardened Runtime, DR zertifikatsgebunden |

## Der Befund, der zuerst kam: ohne Entitlement kein Dialog

Der erste Lauf endete nach vier Sekunden mit `denied` — **ohne dass ein Dialog
erschien**. Das Systemprotokoll nennt den Grund wörtlich:

> `Prompting policy for hardened runtime; service: kTCCServiceCalendar requires`
> `entitlement com.apple.security.personal-information.calendars but it is missing`
>
> `Policy disallows prompt for Sub:{de.jarvis.calendar-spike.probe-app}…;`
> `access to kTCCServiceCalendar denied`

Unter Hardened Runtime verlangt macOS das Entitlement, **bevor** es überhaupt
fragt. Fehlt es, gibt es keine Ablehnung durch den Menschen, sondern eine
stille Ablehnung durch die Richtlinie — von außen ununterscheidbar von „der
Nutzer hat nein gesagt". Ein `NSCalendarsUsageDescription` allein genügt nicht.

Dieselbe Protokollzeile erschien für `kTCCServiceAddressBook`: Die Jarvis-App
trägt `com.apple.security.personal-information.addressbook` bereits, und genau
deshalb funktionieren die Kontakte. Das Kalender-Pendant fehlt ihr noch.

Nach `codesign --entitlements` mit
`com.apple.security.personal-information.calendars` erschien der Dialog, die
Berechtigung wurde erteilt, und der zweite Lauf fragte nicht erneut.

## Ergebnis des Lesens

Fenster: 30 Tage zurück, 90 Tage voraus (2026-07-05 bis 2026-11-02).

| Kalender | Anzahl |
|---|---|
| gesamt | 11 |
| davon schreibbar | 9 |
| davon abonniert (nur lesbar) | 1 |
| davon unveränderlich (Geburtstage) | 1 |
| Arten | 9 × calDAV, 1 × subscription, 1 × birthday |
| Quellenarten | 9 × calDAV, 1 × subscribed, 1 × birthdays |
| verschiedene Quellen | 3 |

| Termine im Fenster | Anzahl |
|---|---|
| gesamt | 16 |
| ganztägig | 12 |
| mit Wiederholungsregel | 9 |
| abgelöste Einzeltermine (Ausnahmen) | 0 |
| mit Teilnehmern | 0 |
| mit Wecker | 16 |
| mit Notiz | 5 |
| mit Ort | 1 |
| mit URL | 6 |
| **mit gesetzter Zeitzone** | **4** |
| abgesagt | 0 |
| ohne `eventIdentifier` | 0 |
| ohne `calendarItemExternalIdentifier` | 0 |
| Kennungskollisionen (beide Arten) | 0 |

Nur 4 von 16 Terminen tragen eine Zeitzone. Das ist kein Mangel, sondern der
Normalfall: ganztägige und „schwebende" Termine haben keine. Wer sie beim
Import nach UTC normalisiert, verschiebt sie beim nächsten Ortswechsel.

## Der Befund, der die Architektur entscheidet

Zweiter Versuch: Das signierte Bündel startet das **nackte, unsignierte**
CLI-Binary daneben — kein eigenes Bündel, kein eigenes Entitlement, keine
eigene TCC-Kennung — und lässt es lesen.

```
"parent_authorization_status": "authorized",
"child_binary_is_bundled": false,
"child_exit_code": 0,
"child": { "ok": true, "authorization_status": "authorized",
           "calendar_count": 11 }
```

Das Kind sah denselben Bestand wie das Elternteil. **TCC urteilt über den
verantwortlichen Prozess, nicht über die Kennung des Kindes.** Ein
Sidecar- oder Helferprozess ist damit möglich, solange die App ihn startet und
die App das Entitlement trägt.

## Datenschutz

Der Bericht enthält Zählungen, Merkmalsverteilungen und maskierte Verweise
(`K-…` Kalender, `S-…` Quelle, dieselbe Bildung wie `C-…` im Kontaktmodul).
Kein Titel, kein Ort, keine Notiz, keine Teilnehmerin, keine Uhrzeit eines
einzelnen Termins, keine rohe Kennung. Vier Tests prüfen das an den
abgelegten Berichten nach, statt es zu behaupten.

## Nicht bewiesen

* **ARM64.** Keine Zeile dieses Berichts gilt für Apple Silicon (DEC-042).
* **TCC-Persistenz** über Rebuild, Versions-Bump, Verschieben und Quarantäne —
  geprüft ist nur, dass ein zweiter Lauf desselben Artefakts nicht erneut fragt.
* **Schreiben.** Ausdrücklich nicht Gegenstand dieses Spikes.
* **Große Bestände.** 11 Kalender, 16 Termine im Fenster. Über Laufzeit und
  Speicherverhalten bei tausenden Terminen sagt das nichts.

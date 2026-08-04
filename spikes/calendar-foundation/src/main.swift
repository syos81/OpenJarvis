// main.swift — SPIKE „Kalender-Fundament" (Intel, 2026-08-04). Temporär, nicht produktiv.
//
// **Zweck.** Beweisen, dass sich Kalender und Termine auf diesem Gerät lesen
// lassen, und dabei genau die Befunde einsammeln, die das Datenmodell und den
// Sync-Vertrag entscheiden. Nichts anderes.
//
// **Diese Datei schreibt nicht.** Es gibt keinen `EKEvent(eventStore:)`, kein
// `save`, kein `remove`, keinen `commit`. Wer hier eine Mutation ergänzt, bricht
// die Auftragsgrenze — der Spike ist ausdrücklich read-only.
//
// **Und sie gibt keine Inhalte heraus.** Kein Titel, kein Ort, keine Notiz,
// keine Teilnehmerin, keine Uhrzeit eines einzelnen Termins, keine rohe
// Kennung. Nur Zählungen, Merkmalsverteilungen und maskierte Verweise
// (`K-…` Kalender, `S-…` Quelle) — dieselbe Bildung wie `C-…` im Kontaktmodul.
// Das ist keine Kosmetik: der Bericht wandert in ein Repository.

import EventKit
import Foundation
import CryptoKit

// ── Maskierung ───────────────────────────────────────────────────────────────

func maskiere(_ praefix: String, _ roh: String) -> String {
    if roh.isEmpty { return "\(praefix)-leer" }
    let digest = SHA256.hash(data: Data(roh.utf8))
    let hex = digest.map { String(format: "%02x", $0) }.joined()
    return "\(praefix)-\(hex.prefix(12))"
}

// ── Ausgabe ──────────────────────────────────────────────────────────────────

// `--out` gibt es, weil der eigentliche Beweis aus einem per `open` gestarteten
// App-Bündel kommt: dort ist stdout abgehängt. Ohne Pfad bleibt es bei stdout.
func gibAus(_ objekt: [String: Any]) {
    let daten = try! JSONSerialization.data(
        withJSONObject: objekt, options: [.sortedKeys, .prettyPrinted])
    let text = String(data: daten, encoding: .utf8)!
    if let i = CommandLine.arguments.firstIndex(of: "--out"),
       i + 1 < CommandLine.arguments.count {
        let pfad = CommandLine.arguments[i + 1]
        FileManager.default.createFile(
            atPath: pfad, contents: Data(text.utf8),
            attributes: [.posixPermissions: 0o600])
    } else {
        print(text)
    }
}

func autorisierung() -> String {
    switch EKEventStore.authorizationStatus(for: .event) {
    case .notDetermined: return "notDetermined"
    case .restricted:    return "restricted"
    case .denied:        return "denied"
    case .authorized:    return "authorized"
    @unknown default:    return "unknown"
    }
}

func kalenderArt(_ typ: EKCalendarType) -> String {
    switch typ {
    case .local:        return "local"
    case .calDAV:       return "calDAV"
    case .exchange:     return "exchange"
    case .subscription: return "subscription"
    case .birthday:     return "birthday"
    @unknown default:   return "unknown"
    }
}

func quellenArt(_ typ: EKSourceType) -> String {
    switch typ {
    case .local:        return "local"
    case .exchange:     return "exchange"
    case .calDAV:       return "calDAV"
    case .mobileMe:     return "mobileMe"
    case .subscribed:   return "subscribed"
    case .birthdays:    return "birthdays"
    @unknown default:   return "unknown"
    }
}

// ── Modus `caps`: berührt den Store nicht ────────────────────────────────────
//
// Wichtig für die Prozessortfrage: `authorizationStatus` löst keinen Dialog aus
// und instanziiert keinen Store. Der Modus ist damit in jedem Prozess gefahrlos.

func modusCaps() {
    let info = ProcessInfo.processInfo
    gibAus([
        "mode": "caps",
        "eventkit_available": true,
        "authorization_status": autorisierung(),
        "os_version": info.operatingSystemVersionString,
        "arch": {
            #if arch(x86_64)
            return "x86_64"
            #elseif arch(arm64)
            return "arm64"
            #else
            return "unknown"
            #endif
        }(),
        "store_touched": false,
        "write_capable": false,
    ])
}

// ── Modus `probe`: liest ─────────────────────────────────────────────────────

func modusProbe(tageZurueck: Int, tageVoraus: Int) {
    let store = EKEventStore()

    // Zugriff anfordern. Auf macOS 12 gibt es nur die eine Stufe für `.event`;
    // die Trennung Voll-/Schreibzugriff kam erst mit macOS 14.
    var erlaubt = false
    var fehlerText: String? = nil
    let tor = DispatchSemaphore(value: 0)
    store.requestAccess(to: .event) { ok, fehler in
        erlaubt = ok
        if let f = fehler { fehlerText = "\(type(of: f))" }
        tor.signal()
    }
    if tor.wait(timeout: .now() + 60) == .timedOut {
        gibAus(["mode": "probe", "ok": false, "reason": "authorization_timeout"])
        exit(3)
    }
    guard erlaubt else {
        gibAus([
            "mode": "probe", "ok": false, "reason": "authorization_denied",
            "authorization_status": autorisierung(),
            "error_class": fehlerText ?? "",
        ])
        exit(4)
    }

    // ── Kalenderinventar ────────────────────────────────────────────────────
    let kalender = store.calendars(for: .event)
    var artHistogramm: [String: Int] = [:]
    var quellenHistogramm: [String: Int] = [:]
    var schreibbar = 0
    var abonniert = 0
    var unveraenderlich = 0
    var kalenderZeilen: [[String: Any]] = []

    for k in kalender {
        let art = kalenderArt(k.type)
        artHistogramm[art, default: 0] += 1
        let qArt = k.source.map { quellenArt($0.sourceType) } ?? "unknown"
        quellenHistogramm[qArt, default: 0] += 1
        if k.allowsContentModifications { schreibbar += 1 }
        if k.isSubscribed { abonniert += 1 }
        if k.isImmutable { unveraenderlich += 1 }
        kalenderZeilen.append([
            "calendar_ref": maskiere("K", k.calendarIdentifier),
            "source_ref": maskiere("S", k.source?.sourceIdentifier ?? ""),
            "calendar_type": art,
            "source_type": qArt,
            "allows_modifications": k.allowsContentModifications,
            "is_subscribed": k.isSubscribed,
            "is_immutable": k.isImmutable,
            "supports_events": k.allowedEntityTypes.contains(.event),
        ])
    }
    kalenderZeilen.sort {
        ($0["calendar_ref"] as! String) < ($1["calendar_ref"] as! String)
    }

    // Der Standardkalender ist die einzige Vorbelegung, die EventKit anbietet.
    let standard = store.defaultCalendarForNewEvents.map {
        maskiere("K", $0.calendarIdentifier)
    }

    // ── Terminfenster ───────────────────────────────────────────────────────
    //
    // EventKit kennt keinen „alle Termine"-Aufruf: gelesen wird immer über ein
    // Zeitfenster. Genau das ist der Grund, warum der Sync-Vertrag des Moduls
    // ein Fenster braucht und keinen Cursor bekommt.
    let jetzt = Date()
    let start = Calendar.current.date(byAdding: .day, value: -tageZurueck, to: jetzt)!
    let ende  = Calendar.current.date(byAdding: .day, value:  tageVoraus,  to: jetzt)!
    let praedikat = store.predicateForEvents(withStart: start, end: ende,
                                             calendars: kalender.isEmpty ? nil : kalender)
    let termine = store.events(matching: praedikat)

    var ganztaegig = 0, wiederkehrend = 0, abgeloest = 0
    var mitTeilnehmern = 0, mitAlarm = 0, mitNotiz = 0, mitOrt = 0, mitUrl = 0
    var mitZeitzone = 0, abgesagt = 0, ohneEventIdentifier = 0, ohneExternalId = 0
    var proKalender: [String: Int] = [:]
    var externalIdZaehler: [String: Int] = [:]
    var eventIdZaehler: [String: Int] = [:]

    for e in termine {
        if e.isAllDay { ganztaegig += 1 }
        if e.hasRecurrenceRules { wiederkehrend += 1 }
        if e.isDetached { abgeloest += 1 }
        if e.hasAttendees { mitTeilnehmern += 1 }
        if e.hasAlarms { mitAlarm += 1 }
        if e.hasNotes { mitNotiz += 1 }
        if !(e.location ?? "").isEmpty { mitOrt += 1 }
        if e.url != nil { mitUrl += 1 }
        if e.timeZone != nil { mitZeitzone += 1 }
        if e.status == .canceled { abgesagt += 1 }

        let eid = e.eventIdentifier ?? ""
        if eid.isEmpty { ohneEventIdentifier += 1 } else { eventIdZaehler[eid, default: 0] += 1 }
        let xid = e.calendarItemExternalIdentifier ?? ""
        if xid.isEmpty { ohneExternalId += 1 } else { externalIdZaehler[xid, default: 0] += 1 }

        proKalender[maskiere("K", e.calendar.calendarIdentifier), default: 0] += 1
    }

    // Die beiden Zahlen entscheiden das External-ID-Modell: teilen sich mehrere
    // gelesene Datensätze eine Kennung, taugt sie nicht als Primärschlüssel.
    let eventIdMehrfach = eventIdZaehler.values.filter { $0 > 1 }.count
    let externalIdMehrfach = externalIdZaehler.values.filter { $0 > 1 }.count

    let formatierer = ISO8601DateFormatter()
    gibAus([
        "mode": "probe",
        "ok": true,
        "authorization_status": autorisierung(),
        "calendars": [
            "count": kalender.count,
            "writable": schreibbar,
            "subscribed": abonniert,
            "immutable": unveraenderlich,
            "by_type": artHistogramm,
            "by_source_type": quellenHistogramm,
            "default_for_new_events": standard ?? "",
            "rows": kalenderZeilen,
        ],
        "window": [
            "start": formatierer.string(from: start),
            "end": formatierer.string(from: ende),
            "days_back": tageZurueck,
            "days_forward": tageVoraus,
        ],
        "events": [
            "count": termine.count,
            "all_day": ganztaegig,
            "recurring": wiederkehrend,
            "detached_occurrences": abgeloest,
            "with_attendees": mitTeilnehmern,
            "with_alarms": mitAlarm,
            "with_notes": mitNotiz,
            "with_location": mitOrt,
            "with_url": mitUrl,
            "with_timezone": mitZeitzone,
            "cancelled": abgesagt,
            "missing_event_identifier": ohneEventIdentifier,
            "missing_external_identifier": ohneExternalId,
            "event_identifier_collisions": eventIdMehrfach,
            "external_identifier_collisions": externalIdMehrfach,
            "per_calendar": proKalender,
        ],
        "write_attempted": false,
    ])
}

// ── Modus `spawn`: die Architekturfrage ──────────────────────────────────────
//
// Läuft im App-Bündel und startet das **nackte** CLI-Binary daneben (kein
// Bündel, kein eigenes Entitlement) mit `probe`. Erbt das Kind den Zugriff,
// taugt ein Sidecar; erbt es ihn nicht, muss das Lesen im Bündelprozess selbst
// stattfinden. Genau das entscheidet, wo der Lesepfad des Moduls wohnt.

func modusSpawn(kindPfad: String, ausgabe: String) {
    let kind = Process()
    kind.executableURL = URL(fileURLWithPath: kindPfad)
    kind.arguments = ["probe", "--out", ausgabe + ".child"]
    var start: String? = nil
    do { try kind.run() } catch { start = "\(error)" }
    if start == nil { kind.waitUntilExit() }

    var kindBericht: Any = ""
    if let daten = FileManager.default.contents(atPath: ausgabe + ".child"),
       let objekt = try? JSONSerialization.jsonObject(with: daten) {
        // Nur die Antwort auf die Architekturfrage übernehmen, nicht den
        // ganzen zweiten Bestandsbericht.
        if let d = objekt as? [String: Any] {
            kindBericht = [
                "ok": d["ok"] ?? false,
                "authorization_status": d["authorization_status"] ?? "",
                "reason": d["reason"] ?? "",
                "calendar_count": (d["calendars"] as? [String: Any])?["count"] ?? 0,
            ]
        }
    }
    gibAus([
        "mode": "spawn",
        "parent_authorization_status": autorisierung(),
        "child_binary_is_bundled": false,
        "child_launch_error": start ?? "",
        "child_exit_code": start == nil ? Int(kind.terminationStatus) : -1,
        "child": kindBericht,
    ])
}

// ── Einstieg ─────────────────────────────────────────────────────────────────

let argumente = Array(CommandLine.arguments.dropFirst())
let modus = argumente.first ?? "caps"

func zahl(_ name: String, _ vorgabe: Int) -> Int {
    guard let i = argumente.firstIndex(of: name), i + 1 < argumente.count,
          let wert = Int(argumente[i + 1]) else { return vorgabe }
    return max(0, min(3650, wert))
}

switch modus {
case "caps":
    modusCaps()
case "probe":
    modusProbe(tageZurueck: zahl("--days-back", 30),
               tageVoraus: zahl("--days-forward", 90))
case "spawn":
    func text(_ name: String) -> String {
        guard let i = argumente.firstIndex(of: name), i + 1 < argumente.count
        else { return "" }
        return argumente[i + 1]
    }
    modusSpawn(kindPfad: text("--child-binary"), ausgabe: text("--out"))
default:
    FileHandle.standardError.write(
        "Nutzung: jarvis-calendar-probe [caps|probe] [--days-back N] [--days-forward N]\n"
            .data(using: .utf8)!)
    exit(2)
}

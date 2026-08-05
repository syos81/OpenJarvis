//  sidecar.swift — produktive Kalender-Bridge (Modul 2, Baseline §3 A-3/A-4).
//
//  Dünner Sidecar: JSON-Lines über stdin/stdout, exakt nach dem Muster der
//  Kontakte-Bridge (ADR-0016 Punkt 4). Transport, Prozessführung und
//  Fehlerklassen teilt er sich mit ihr; verschieden ist nur der Fachvertrag.
//
//  ERLAUBT: EKEventStore-Lesezugriffe, providerneutrale DTOs, technische
//  Fehlercodes aus geschlossener Menge, deterministische Serialisierung.
//
//  VERBOTEN: Fachlogik, Workspaces, Zuordnungen, Konflikt- oder
//  Risikobewertung, Audit, kanonische Speicherung, Normalisierung, Hashing
//  (auch kein Felddigest — der entsteht im Kern), Anzeigenamen-Bildung.
//
//  VERBOTEN in v1 zusätzlich: **jede Schreiboperation.** Es gibt keinen
//  `save`-, `remove`- oder `commit`-Aufruf in dieser Datei; ein Test prüft
//  das an der Quelle, ein zweiter am gebauten Binary (Baseline §2 B-3/B-4:
//  der volle Umfang kommt, aber der Schreibvertrag entsteht mit dem
//  Schreibauftrag — nicht nebenbei).
//
//  stdout = ausschließlich Protokoll. Alle Diagnosen nach stderr, ohne PII.

import Foundation
import EventKit

// ── Protokollkonstanten ───────────────────────────────────────────────────────
let kProtocolVersion = 1
let kBundleIdentifier = "de.kluender.jarvis.calendar-bridge"
let kKeySetVersion = 1

// ── Ausgabe ───────────────────────────────────────────────────────────────────
let stdoutLock = NSLock()

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(
        withJSONObject: obj, options: [.sortedKeys, .withoutEscapingSlashes]),
          let line = String(data: data, encoding: .utf8) else {
        diag("Antwort nicht serialisierbar")
        return
    }
    stdoutLock.lock()
    FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    stdoutLock.unlock()
}

/// Diagnose nach stderr. Niemals PII: keine Titel, Orte, Notizen, Teilnehmer,
/// Identifier oder Payloads. Der Marker ist zugleich der `stderr_prefix` des
/// gemeinsamen `SidecarContract` — alles ohne ihn gilt dem Host als fremd.
func diag(_ s: String) {
    FileHandle.standardError.write(("[calendar-bridge] " + s + "\n").data(using: .utf8)!)
}

// ── Geschlossene Fehlermenge (Abbildung auf CapabilityError im Kern) ─────────
enum ErrCode: String {
    case tccDenied        = "tcc_denied"
    case notFound         = "not_found"
    case invalidRequest   = "invalid_request"
    case forbidden        = "forbidden"
    case providerError    = "provider_error"
    case unsupported      = "unsupported"
    case internalError    = "internal"
    case notImplemented   = "not_implemented"
    case protocolMismatch = "protocol_mismatch"
}

func ok(_ id: Any, _ result: [String: Any]) {
    emit(["protocolVersion": kProtocolVersion, "requestId": id,
          "ok": true, "result": result])
}

func fail(_ id: Any, _ code: ErrCode, _ message: String, retryable: Bool = false) {
    emit(["protocolVersion": kProtocolVersion, "requestId": id, "ok": false,
          "error": ["code": code.rawValue, "message": message,
                    "retryable": retryable]])
}

func stream(_ id: Any, _ item: [String: Any]) {
    emit(["protocolVersion": kProtocolVersion, "requestId": id,
          "stream": "item", "item": item])
}

// ── Autorisierung ─────────────────────────────────────────────────────────────
//
// Über ROHWERTE, nicht über Enum-Fälle. Das ist der Kern der SDK-Verträglich-
// keit aus Baseline B-12: `EKAuthorizationStatus.fullAccess` existiert im
// macOS-13.1-SDK des Intel-Rechners nicht und darf im Quelltext nicht
// vorkommen — `.fullAccess` und `.authorized` teilen sich aber ohnehin den
// Rohwert 3. Neu ist allein `.writeOnly` (4). Der alte Jarvis-Kalender scheiterte
// genau hier: sein `@unknown default` meldete jeden neuen Wert als `unknown`,
// woraufhin das authorized-Gate trotz erteiltem Vollzugriff schloss.
//
// Rohwerte laut EventKit: 0 notDetermined · 1 restricted · 2 denied ·
// 3 authorized/fullAccess · 4 writeOnly.
func authStatusText() -> String {
    switch EKEventStore.authorizationStatus(for: .event).rawValue {
    case 0:  return "not_determined"
    case 1:  return "restricted"
    case 2:  return "denied"
    case 3:  return "full_access"
    case 4:  return "write_only"
    default: return "unknown"
    }
}

/// Lesen setzt Vollzugriff voraus. `write_only` genügt ausdrücklich **nicht**
/// und wird nie als Leseberechtigung gewertet (fail-closed).
func canRead() -> Bool {
    return EKEventStore.authorizationStatus(for: .event).rawValue == 3
}

let store = EKEventStore()

/// Fordert die Berechtigung an — **nur** auf ausdrückliche Nutzeraktion.
///
/// Ein gemeinsamer Quelltext für beide SDK-Stände: `requestFullAccessToEvents`
/// existiert erst ab macOS 14 und ist im 13.1-SDK nicht einmal deklariert, ein
/// `#available` würde also gar nicht erst kompilieren. Deshalb wird der
/// Selektor zur Laufzeit gesucht. Gibt es ihn, wird er benutzt; sonst der
/// klassische Weg. Beide Zweige stehen in derselben Datei — die Bridge muss
/// nicht je Zielsystem anders gebaut werden (Baseline B-12, B-15).
func requestAccess(_ completion: @escaping (Bool, Error?) -> Void) {
    let modern = NSSelectorFromString("requestFullAccessToEventsWithCompletion:")
    if store.responds(to: modern) {
        typealias Handler = @convention(block) (Bool, Error?) -> Void
        let block: Handler = { granted, error in completion(granted, error) }
        diag("requestAuthorization: moderner Pfad (macOS 14+)")
        _ = store.perform(modern, with: block)
        return
    }
    diag("requestAuthorization: klassischer Pfad (macOS 12/13)")
    store.requestAccess(to: .event) { granted, error in completion(granted, error) }
}

// ── Formatierung ──────────────────────────────────────────────────────────────
let isoFormatter: ISO8601DateFormatter = {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    f.timeZone = TimeZone(identifier: "UTC")
    return f
}()

func iso(_ date: Date?) -> Any {
    guard let date else { return NSNull() }
    return isoFormatter.string(from: date)
}

func orNull(_ s: String?) -> Any {
    guard let s, !s.isEmpty else { return NSNull() }
    return s
}

/// Kalenderfarbe als stabiles `#rrggbb`. Rein visuell; ohne lesbare Farbe
/// ehrlich `null` statt eines erfundenen Vorgabewerts.
func hexColor(_ cgColor: CGColor?) -> Any {
    guard let cgColor,
          let space = CGColorSpace(name: CGColorSpace.sRGB),
          let converted = cgColor.converted(to: space, intent: .defaultIntent,
                                            options: nil),
          let c = converted.components, c.count >= 3 else { return NSNull() }
    let clamp = { (v: CGFloat) -> Int in Int((max(0, min(1, v)) * 255).rounded()) }
    return String(format: "#%02x%02x%02x", clamp(c[0]), clamp(c[1]), clamp(c[2]))
}

func calendarTypeText(_ t: EKCalendarType) -> String {
    switch t {
    case .local:        return "local"
    case .calDAV:       return "calDAV"
    case .exchange:     return "exchange"
    case .subscription: return "subscription"
    case .birthday:     return "birthday"
    @unknown default:   return "unknown"
    }
}

func sourceTypeText(_ t: EKSourceType) -> String {
    switch t {
    case .local:        return "local"
    case .exchange:     return "exchange"
    case .calDAV:       return "calDAV"
    case .mobileMe:     return "mobileMe"
    case .subscribed:   return "subscribed"
    case .birthdays:    return "birthdays"
    @unknown default:   return "unknown"
    }
}

func eventStatusText(_ s: EKEventStatus) -> String {
    switch s {
    case .none:      return "none"
    case .confirmed: return "confirmed"
    case .tentative: return "tentative"
    case .canceled:  return "canceled"
    @unknown default: return "unknown"
    }
}

func availabilityText(_ a: EKEventAvailability) -> String {
    switch a {
    case .notSupported: return "not_supported"
    case .busy:         return "busy"
    case .free:         return "free"
    case .tentative:    return "tentative"
    case .unavailable:  return "unavailable"
    @unknown default:   return "unknown"
    }
}

func participantRoleText(_ r: EKParticipantRole) -> String {
    switch r {
    case .unknown:       return "unknown"
    case .required:      return "required"
    case .optional:      return "optional"
    case .chair:         return "chair"
    case .nonParticipant: return "non_participant"
    @unknown default:    return "unknown"
    }
}

func participantStatusText(_ s: EKParticipantStatus) -> String {
    switch s {
    case .unknown:   return "unknown"
    case .pending:   return "pending"
    case .accepted:  return "accepted"
    case .declined:  return "declined"
    case .tentative: return "tentative"
    case .delegated: return "delegated"
    case .completed: return "completed"
    case .inProcess: return "in_process"
    @unknown default: return "unknown"
    }
}

func participantTypeText(_ t: EKParticipantType) -> String {
    switch t {
    case .unknown:  return "unknown"
    case .person:   return "person"
    case .room:     return "room"
    case .resource: return "resource"
    case .group:    return "group"
    @unknown default: return "unknown"
    }
}

/// Die Rohadresse eines Teilnehmers. EventKit gibt sie auf macOS nur über die
/// `mailto:`-URL heraus; ein öffentliches `emailAddress` gibt es hier nicht.
/// Es wird **nichts** normalisiert oder kleingeschrieben — das ist Kernarbeit.
func participantAddress(_ p: EKParticipant) -> Any {
    let raw = p.url.absoluteString
    guard raw.lowercased().hasPrefix("mailto:") else { return orNull(raw) }
    return orNull(String(raw.dropFirst("mailto:".count)))
}

func participantDTO(_ p: EKParticipant, isOrganizer: Bool) -> [String: Any] {
    return [
        "rawAddress":        participantAddress(p),
        "displayName":       orNull(p.name),
        "role":              participantRoleText(p.participantRole),
        "participantStatus": participantStatusText(p.participantStatus),
        "participantType":   participantTypeText(p.participantType),
        "isCurrentUser":     p.isCurrentUser,
        "isOrganizer":       isOrganizer,
    ]
}

/// Wecker roh. `EKAlarm` trägt entweder einen absoluten Zeitpunkt **oder**
/// einen relativen Versatz zum Beginn — beides wird unverändert übernommen.
func alarmDTO(_ a: EKAlarm) -> [String: Any] {
    return [
        "absoluteDate":   iso(a.absoluteDate),
        "relativeOffset": a.absoluteDate == nil ? a.relativeOffset : NSNull(),
    ]
}

/// Die Wiederholungsregel **roh** (Baseline: Regel ist Wahrheit, Instanzen
/// sind abgeleiteter Cache). EventKit gibt keinen RFC-5545-Text heraus, also
/// werden die Bestandteile strukturiert übernommen — nichts wird gedeutet,
/// nichts materialisiert.
func recurrenceDTO(_ r: EKRecurrenceRule) -> [String: Any] {
    func numbers(_ v: [NSNumber]?) -> Any {
        guard let v, !v.isEmpty else { return NSNull() }
        return v.map { $0.intValue }
    }
    var end: Any = NSNull()
    if let e = r.recurrenceEnd {
        if let until = e.endDate {
            end = ["type": "until", "until": iso(until)]
        } else {
            end = ["type": "count", "count": Int(e.occurrenceCount)]
        }
    }
    var daysOfWeek: Any = NSNull()
    if let days = r.daysOfTheWeek, !days.isEmpty {
        daysOfWeek = days.map { ["dayOfTheWeek": $0.dayOfTheWeek.rawValue,
                                 "weekNumber": $0.weekNumber] }
    }
    return [
        "frequency": {
            switch r.frequency {
            case .daily:   return "daily"
            case .weekly:  return "weekly"
            case .monthly: return "monthly"
            case .yearly:  return "yearly"
            @unknown default: return "unknown"
            }
        }(),
        "interval":          r.interval,
        "firstDayOfTheWeek": r.firstDayOfTheWeek,
        "daysOfTheWeek":     daysOfWeek,
        "daysOfTheMonth":    numbers(r.daysOfTheMonth),
        "daysOfTheYear":     numbers(r.daysOfTheYear),
        "weeksOfTheYear":    numbers(r.weeksOfTheYear),
        "monthsOfTheYear":   numbers(r.monthsOfTheYear),
        "setPositions":      numbers(r.setPositions),
        "end":               end,
    ]
}

func calendarDTO(_ c: EKCalendar) -> [String: Any] {
    var source: Any = NSNull()
    if let s = c.source {
        // Nur technische Kennung, Anzeigename und Art — **keine** Apple-ID,
        // keine Mailadresse, keine Zugangsdaten.
        source = ["sourceIdentifier": s.sourceIdentifier,
                  "title": s.title,
                  "sourceType": sourceTypeText(s.sourceType)]
    }
    return [
        "calendarIdentifier":         c.calendarIdentifier,
        "title":                      c.title,
        "calendarType":               calendarTypeText(c.type),
        "color":                      hexColor(c.cgColor),
        "isSubscribed":               c.isSubscribed,
        "isImmutable":                c.isImmutable,
        "allowsContentModifications": c.allowsContentModifications,
        "allowedEntityTypes":         c.allowedEntityTypes.contains(.event),
        "source":                     source,
    ]
}

func eventDTO(_ e: EKEvent) -> [String: Any] {
    // Zeitzone bleibt **nullable**: ganztägige und schwebende Termine haben
    // keine, und sie nach UTC zu normalisieren verschöbe sie beim nächsten
    // Ortswechsel (Baseline B-7). Der Sidecar erfindet hier nichts.
    let tz: Any = e.timeZone.map { $0.identifier } ?? NSNull()

    var attendees: [[String: Any]] = []
    if let list = e.attendees {
        let organizerURL = e.organizer?.url.absoluteString
        attendees = list.map {
            participantDTO($0, isOrganizer: $0.url.absoluteString == organizerURL)
        }
    }
    if let organizer = e.organizer,
       !attendees.contains(where: { ($0["isOrganizer"] as? Bool) == true }) {
        attendees.append(participantDTO(organizer, isOrganizer: true))
    }

    var recurrence: Any = NSNull()
    if let rules = e.recurrenceRules, let first = rules.first {
        // EventKit erlaubt mehrere Regeln; in der Praxis liefert Apple genau
        // eine. Weitere werden gezählt, damit der Kern den Fall bemerkt,
        // statt ihn stillschweigend zu verlieren.
        recurrence = recurrenceDTO(first)
    }

    return [
        "providerIdentifier":       orNull(e.eventIdentifier),
        "calendarItemIdentifier":   orNull(e.calendarItemIdentifier),
        // Die CalDAV-UID ist ausdrücklich **nicht** eindeutig: derselbe Termin
        // erscheint bei Einladungen in mehreren Kalendern. Korrelationshinweis,
        // nie Primärschlüssel.
        "externalUid":              orNull(e.calendarItemExternalIdentifier),
        "calendarIdentifier":       orNull(e.calendar?.calendarIdentifier),
        "title":                    orNull(e.title),
        "notes":                    orNull(e.notes),
        "location":                 orNull(e.location),
        "url":                      orNull(e.url?.absoluteString),
        "startsAtUtc":              iso(e.startDate),
        "endsAtUtc":                iso(e.endDate),
        "timeZone":                 tz,
        "isAllDay":                 e.isAllDay,
        "status":                   eventStatusText(e.status),
        "availability":             availabilityText(e.availability),
        "hasRecurrenceRules":       e.hasRecurrenceRules,
        "recurrenceRuleCount":      e.recurrenceRules?.count ?? 0,
        "recurrenceRule":           recurrence,
        "isDetached":               e.isDetached,
        "occurrenceStartUtc":       iso(e.occurrenceDate),
        "hasAlarms":                (e.alarms?.isEmpty == false),
        "alarms":                   (e.alarms ?? []).map(alarmDTO),
        "hasAttendees":             !attendees.isEmpty,
        "attendees":                attendees,
        "createdAtUtc":             iso(e.creationDate),
        "lastModifiedAtUtc":        iso(e.lastModifiedDate),
    ]
}

// ── Fähigkeiten ───────────────────────────────────────────────────────────────
//
// Ehrliche Grenzen statt Verschweigen (08 §3 Nr. 2/7). `changeFeed:
// "notification"` ist der teuerste Unterschied zu den Kontakten: EventKit hat
// kein Gegenstück zu `CNChangeHistory`. `EKEventStoreChangedNotification` sagt
// „schau nach", nie „das hat sich geändert" — wer sie als Delta behandelt,
// verliert Änderungen. Deshalb ist `windowRequired` true und der Voll-Diff je
// Fenster der Normalbetrieb, nicht der Notfall.
func capabilities() -> [String: Any] {
    return [
        "canRead":               true,
        "canCreateEvents":       false,
        "canUpdateEvents":       false,
        "canDeleteEvents":       false,
        "supportsRecurrence":    true,
        "supportsAttendees":     true,
        "supportsAlarms":        true,
        "supportsFreeBusy":      false,
        "supportsTimeZones":     true,
        "windowRequired":        true,
        "changeFeed":            "notification",
        "mutationsImplemented":  false,
    ]
}

func handshakePayload() -> [String: Any] {
    return [
        "type": "ready",
        "protocolVersion": kProtocolVersion,
        "bundleIdentifier": kBundleIdentifier,
        "keySetVersion": kKeySetVersion,
        "authorizationStatus": authStatusText(),
        "operations": ["ping", "caps", "authorizationStatus",
                       "requestAuthorization", "calendars", "events",
                       "shutdown"],
        "capabilities": capabilities(),
    ]
}

// ── Operationen ───────────────────────────────────────────────────────────────
func opAuthorizationStatus(_ id: Any) {
    ok(id, ["authorizationStatus": authStatusText()])
}

func opRequestAuthorization(_ id: Any, _ payload: [String: Any]) {
    // Ausschliesslich auf ausdrueckliche Nutzeraktion. Es gibt kein Env-Gate
    // und keinen impliziten Weg; ein Start des Sidecars fragt **nie**.
    guard (payload["request"] as? Bool) == true else {
        fail(id, .invalidRequest, "payload.request muss true sein")
        return
    }
    let before = authStatusText()
    if before != "not_determined" {
        // Bereits entschieden: macOS zeigt keinen Dialog mehr. Ehrlich melden,
        // statt einen Versuch zu behaupten, den es nicht gab.
        ok(id, ["granted": before == "full_access",
                "authorizationStatus": before, "promptAttempted": false])
        return
    }
    let semaphore = DispatchSemaphore(value: 0)
    requestAccess { _, _ in semaphore.signal() }
    // Ohne Frist hielte ein nie beantworteter Dialog den Prozess ewig.
    _ = semaphore.wait(timeout: .now() + 300)
    let after = authStatusText()
    ok(id, ["granted": after == "full_access",
            "authorizationStatus": after, "promptAttempted": true])
}

func opCalendars(_ id: Any) {
    guard canRead() else {
        fail(id, .tccDenied, "Kalenderzugriff nicht erteilt (Status \(authStatusText()))")
        return
    }
    let calendars = store.calendars(for: .event)
    // Stabile Reihenfolge: der Host darf sich auf Determinismus verlassen.
    let sorted = calendars.sorted {
        $0.title == $1.title ? $0.calendarIdentifier < $1.calendarIdentifier
                             : $0.title < $1.title
    }
    ok(id, ["calendars": sorted.map(calendarDTO),
            "count": sorted.count,
            "keySetVersion": kKeySetVersion])
}

/// Fensterlesung. Es gibt in EventKit kein „alle Termine" — gelesen wird immer
/// über einen Zeitraum. Das Fenster ist deshalb Pflicht und wird in der Antwort
/// **wiederholt**: ein Bericht ohne Fensterangabe wäre wertlos, weil „nicht
/// gesehen" ohne ihn nicht von „gelöscht" zu unterscheiden ist.
func opEvents(_ id: Any, _ payload: [String: Any]) {
    guard canRead() else {
        fail(id, .tccDenied, "Kalenderzugriff nicht erteilt (Status \(authStatusText()))")
        return
    }
    guard let startRaw = payload["startUtc"] as? String,
          let endRaw = payload["endUtc"] as? String,
          let start = isoFormatter.date(from: startRaw),
          let end = isoFormatter.date(from: endRaw) else {
        fail(id, .invalidRequest, "startUtc und endUtc muessen ISO-8601-UTC sein")
        return
    }
    guard end > start else {
        fail(id, .invalidRequest, "endUtc muss nach startUtc liegen")
        return
    }

    var selected: [EKCalendar]? = nil
    if let wanted = payload["calendarIdentifiers"] as? [String] {
        guard !wanted.isEmpty else {
            fail(id, .invalidRequest, "calendarIdentifiers darf nicht leer sein")
            return
        }
        let all = store.calendars(for: .event)
        let matched = all.filter { wanted.contains($0.calendarIdentifier) }
        guard matched.count == wanted.count else {
            // Fail-closed: ein unbekannter Kalender im Auftrag darf nicht
            // stillschweigend zu einem kleineren Ergebnis führen — sonst sähe
            // ein Teilergebnis wie ein vollständiges aus.
            fail(id, .notFound, "mindestens ein Kalender ist unbekannt")
            return
        }
        selected = matched
    }

    let predicate = store.predicateForEvents(withStart: start, end: end,
                                             calendars: selected)
    let events = store.events(matching: predicate)
    // Deterministische Reihenfolge: Beginn, dann Identifier.
    let sorted = events.sorted {
        if $0.startDate != $1.startDate { return $0.startDate < $1.startDate }
        return ($0.eventIdentifier ?? "") < ($1.eventIdentifier ?? "")
    }
    for e in sorted { stream(id, eventDTO(e)) }
    // `complete: true` ist die Bedingung, unter der der Kern ueberhaupt
    // Loeschungen ableiten darf. Eine ohne sie beendete Lesung ist ungueltig.
    ok(id, ["count": sorted.count,
            "complete": true,
            "windowStartUtc": startRaw,
            "windowEndUtc": endRaw,
            "calendarIdentifiers": selected?.map { $0.calendarIdentifier } ?? NSNull(),
            "keySetVersion": kKeySetVersion])
}

// ── Start ─────────────────────────────────────────────────────────────────────
emit(handshakePayload())
diag("bereit, Protokollversion \(kProtocolVersion), Autorisierung \(authStatusText())")

// ── Hauptschleife: eine JSON-Zeile je Anfrage ────────────────────────────────
while let line = readLine(strippingNewline: true) {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    if trimmed.isEmpty { continue }
    guard let data = trimmed.data(using: .utf8),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        emit(["protocolVersion": kProtocolVersion, "requestId": NSNull(), "ok": false,
              "error": ["code": ErrCode.invalidRequest.rawValue,
                        "message": "Zeile ist kein JSON-Objekt", "retryable": false]])
        continue
    }
    let id = obj["requestId"] ?? NSNull()

    if let v = obj["protocolVersion"] as? Int, v != kProtocolVersion {
        fail(id, .protocolMismatch,
             "Protokollversion \(v) wird nicht unterstuetzt (erwartet \(kProtocolVersion))")
        continue
    }
    guard let op = obj["operation"] as? String else {
        fail(id, .invalidRequest, "operation fehlt"); continue
    }
    let payload = obj["payload"] as? [String: Any] ?? [:]

    switch op {
    case "ping":                 ok(id, ["pong": true])
    case "caps":                 ok(id, handshakePayload())
    case "authorizationStatus":  opAuthorizationStatus(id)
    case "requestAuthorization": opRequestAuthorization(id, payload)
    case "calendars":            opCalendars(id)
    case "events":               opEvents(id, payload)
    case "createEvent", "updateEvent", "deleteEvent":
        // v1 schreibt nicht. Ehrlich `not_implemented` — **ohne** Store-Zugriff
        // und ohne die Andeutung, es sei nur gerade abgeschaltet.
        fail(id, .notImplemented, "Schreiboperationen sind in v1 nicht Bestandteil")
    case "shutdown":
        ok(id, ["bye": true])
        diag("shutdown angefordert")
        exit(0)
    default:
        fail(id, .invalidRequest, "unbekannte Operation")
    }
}

// EOF auf stdin bedeutet Shutdown (verhindert verwaiste Prozesse).
diag("stdin EOF — beende")
exit(0)

//  sidecar.swift — produktive Kontakte-Bridge (ADR-0016, DEC-031).
//
//  Dünner Sidecar: JSON-Lines über stdin/stdout.
//
//  ERLAUBT (ADR-0016 Punkt 4): CNContactStore-Zugriffe, providerneutrale DTOs,
//  technische Fehlercodes aus geschlossener Menge, deterministische
//  Serialisierung.
//
//  VERBOTEN: Fachlogik, Workspaces, Rollen, Merge-Entscheidungen,
//  Risikobewertung, Audit, kanonische Speicherung, Normalisierung, Hashing,
//  Anzeigenamen-Bildung. All das bleibt im Kern.
//
//  stdout = ausschließlich Protokoll. Alle Diagnosen nach stderr, ohne PII.

import Foundation
import Contacts

// ── Protokollkonstanten ───────────────────────────────────────────────────────
let kProtocolVersion = 1
let kBundleIdentifier = "de.kluender.jarvis.contacts-bridge"
let kTransactionAuthor = kBundleIdentifier
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

/// Diagnose nach stderr. Niemals PII: keine Namen, Adressen, Nummern,
/// Identifier oder Payloads.
func diag(_ s: String) {
    FileHandle.standardError.write(("[contacts-bridge] " + s + "\n").data(using: .utf8)!)
}

// ── Geschlossene Fehlermenge (Abbildung auf CapabilityError im Kern) ─────────
enum ErrCode: String {
    case tccDenied       = "tcc_denied"
    case notFound        = "not_found"
    case conflict        = "conflict"
    case invalidRequest  = "invalid_request"
    case forbidden       = "forbidden"
    case providerError   = "provider_error"
    case unsupported     = "unsupported"
    case internalError   = "internal"
    case notImplemented  = "not_implemented"
    case protocolMismatch = "protocol_mismatch"
    case invalidToken    = "invalid_token"
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

// ── Store und Autorisierung ──────────────────────────────────────────────────
let store = CNContactStore()

func authStatusText() -> String {
    switch CNContactStore.authorizationStatus(for: .contacts) {
    case .notDetermined: return "notDetermined"
    case .restricted:    return "restricted"
    case .denied:        return "denied"
    case .authorized:    return "authorized"
    @unknown default:    return "unknown"
    }
}

func requireAuth(_ id: Any) -> Bool {
    if CNContactStore.authorizationStatus(for: .contacts) == .authorized { return true }
    fail(id, .tccDenied, "Kontakte-Autorisierung ist \(authStatusText())")
    return false
}

// ── Capabilities ─────────────────────────────────────────────────────────────
// Ehrliche Grenzen statt Verschweigen (08 §3 Nr. 2/7, ADR-0016 Punkt 5).
//
// notesSupported=false: `CNContactNoteKey` erfordert seit macOS 11 das
// Entitlement com.apple.developer.contacts.notes. Die Bridge fordert diesen
// Schlüssel deshalb NICHT an; ein nicht lesbares Notizfeld wird als
// `unavailable_by_capability` gemeldet — niemals als leere Notiz.
//
// linkUnlinkSupported=false: `CNSaveRequest` besitzt keine Link-/Unlink-API
// (nur add/update/delete für Contact/Group/Member). Belegter Plattformbefund.
func capabilityStates() -> [String: Any] {
    return [
        "notesSupported": false,
        "linkUnlinkSupported": false,
        "unifiedReadOnly": true,
        "meCardReadOnly": true,
        "changeHistorySupported": true,
        "fullDiffFallbackSupported": true,
        "mutationsImplemented": false,   // bis Gate C: not_implemented
    ]
}

// ── Schlüsselsatz ────────────────────────────────────────────────────────────
// `CNContactNoteKey` fehlt bewusst (siehe capabilityStates()).
let fetchKeys: [CNKeyDescriptor] = [
    CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey,
    CNContactMiddleNameKey, CNContactNamePrefixKey, CNContactNameSuffixKey,
    CNContactPreviousFamilyNameKey, CNContactNicknameKey,
    CNContactPhoneticGivenNameKey, CNContactPhoneticFamilyNameKey,
    CNContactOrganizationNameKey, CNContactJobTitleKey,
    CNContactDepartmentNameKey, CNContactBirthdayKey, CNContactDatesKey,
    CNContactEmailAddressesKey, CNContactPhoneNumbersKey,
    CNContactPostalAddressesKey, CNContactUrlAddressesKey,
    CNContactSocialProfilesKey, CNContactInstantMessageAddressesKey,
    CNContactRelationsKey, CNContactImageDataAvailableKey,
    CNContactThumbnailImageDataKey, CNContactTypeKey,
].map { $0 as CNKeyDescriptor }

/// Felder, deren Verfügbarkeit im DTO ausgewiesen wird. `note` steht dauerhaft
/// auf `unavailable_by_capability`, solange notesSupported=false.
func fieldAvailability(_ c: CNContact) -> [String: String] {
    var a: [String: String] = ["note": "unavailable_by_capability"]
    func mark(_ name: String, _ key: String, _ nonEmpty: @autoclosure () -> Bool) {
        if !c.isKeyAvailable(key) { a[name] = "unavailable_by_capability"; return }
        a[name] = nonEmpty() ? "present" : "absent"
    }
    mark("givenName", CNContactGivenNameKey, !c.givenName.isEmpty)
    mark("familyName", CNContactFamilyNameKey, !c.familyName.isEmpty)
    mark("organizationName", CNContactOrganizationNameKey, !c.organizationName.isEmpty)
    mark("birthday", CNContactBirthdayKey, c.birthday != nil)
    mark("emails", CNContactEmailAddressesKey, !c.emailAddresses.isEmpty)
    mark("phones", CNContactPhoneNumbersKey, !c.phoneNumbers.isEmpty)
    mark("postalAddresses", CNContactPostalAddressesKey, !c.postalAddresses.isEmpty)
    mark("urlAddresses", CNContactUrlAddressesKey, !c.urlAddresses.isEmpty)
    mark("socialProfiles", CNContactSocialProfilesKey, !c.socialProfiles.isEmpty)
    mark("instantMessages", CNContactInstantMessageAddressesKey,
         !c.instantMessageAddresses.isEmpty)
    mark("relations", CNContactRelationsKey, !c.contactRelations.isEmpty)
    mark("thumbnail", CNContactThumbnailImageDataKey, c.thumbnailImageData != nil)
    return a
}

// ── DTO: deterministisch, providerneutral ────────────────────────────────────
// Sortierte Schlüssel, explizite Nullwerte, keine locale-abhängige Formatierung.
// KEINE Normalisierung, KEIN Hashing, KEIN Anzeigename — das ist Kernaufgabe.
func jn(_ v: Any?) -> Any { v ?? NSNull() }

func labeled(_ label: String?, _ value: Any) -> [String: Any] {
    ["label": jn(label), "value": value]
}

func dto(_ c: CNContact, meIdentifier: String?) -> [String: Any] {
    var d: [String: Any] = [
        "keySetVersion": kKeySetVersion,
        "providerIdentifier": c.identifier,
        "contactType": c.contactType == .organization ? "organization" : "person",
        "isMeCard": meIdentifier != nil && meIdentifier == c.identifier,
        "fieldAvailability": fieldAvailability(c),
        "fieldCompleteness": "full",
    ]
    if c.isKeyAvailable(CNContactGivenNameKey) {
        d["givenName"] = c.givenName
        d["middleName"] = c.middleName
        d["familyName"] = c.familyName
        d["previousFamilyName"] = c.previousFamilyName
        d["namePrefix"] = c.namePrefix
        d["nameSuffix"] = c.nameSuffix
        d["nickname"] = c.nickname
        d["phoneticGivenName"] = c.phoneticGivenName
        d["phoneticFamilyName"] = c.phoneticFamilyName
    } else {
        d["fieldCompleteness"] = "partial"
    }
    if c.isKeyAvailable(CNContactOrganizationNameKey) {
        d["organizationName"] = c.organizationName
        d["jobTitle"] = c.jobTitle
        d["departmentName"] = c.departmentName
    }
    if c.isKeyAvailable(CNContactEmailAddressesKey) {
        d["emails"] = c.emailAddresses.map { labeled($0.label, $0.value as String) }
    }
    if c.isKeyAvailable(CNContactPhoneNumbersKey) {
        d["phones"] = c.phoneNumbers.map { labeled($0.label, $0.value.stringValue) }
    }
    if c.isKeyAvailable(CNContactPostalAddressesKey) {
        d["postalAddresses"] = c.postalAddresses.map { lv -> [String: Any] in
            let a = lv.value
            return ["label": jn(lv.label), "street": a.street, "city": a.city,
                    "state": a.state, "postalCode": a.postalCode,
                    "country": a.country, "isoCountryCode": a.isoCountryCode]
        }
    }
    if c.isKeyAvailable(CNContactUrlAddressesKey) {
        d["urlAddresses"] = c.urlAddresses.map { labeled($0.label, $0.value as String) }
    }
    if c.isKeyAvailable(CNContactSocialProfilesKey) {
        d["socialProfiles"] = c.socialProfiles.map { lv -> [String: Any] in
            ["label": jn(lv.label), "service": lv.value.service,
             "username": lv.value.username, "urlString": lv.value.urlString]
        }
    }
    if c.isKeyAvailable(CNContactInstantMessageAddressesKey) {
        d["instantMessages"] = c.instantMessageAddresses.map { lv -> [String: Any] in
            ["label": jn(lv.label), "service": lv.value.service,
             "username": lv.value.username]
        }
    }
    if c.isKeyAvailable(CNContactRelationsKey) {
        // Apple liefert Beziehungen als freien Text. Es wird NICHT geraten,
        // auf wen sich der Text bezieht — Auflösung ist Kernaufgabe.
        d["relations"] = c.contactRelations.map { labeled($0.label, $0.value.name) }
    }
    if c.isKeyAvailable(CNContactBirthdayKey) {
        if let b = c.birthday {
            d["birthday"] = ["year": jn(b.year), "month": jn(b.month), "day": jn(b.day)]
        } else {
            d["birthday"] = NSNull()
        }
    }
    if c.isKeyAvailable(CNContactDatesKey) {
        d["dates"] = c.dates.map { lv -> [String: Any] in
            ["label": jn(lv.label), "year": jn(lv.value.year),
             "month": jn(lv.value.month), "day": jn(lv.value.day)]
        }
    }
    if c.isKeyAvailable(CNContactImageDataAvailableKey) {
        d["imageAvailable"] = c.imageDataAvailable
    }
    if c.isKeyAvailable(CNContactThumbnailImageDataKey) {
        if let t = c.thumbnailImageData {
            d["thumbnailBase64"] = t.base64EncodedString()
            d["thumbnailBytes"] = t.count
        } else {
            d["thumbnailBase64"] = NSNull()
            d["thumbnailBytes"] = 0
        }
    }
    return d
}

func meCardIdentifier() -> String? {
    // Nur lesend und ohne Fehlerabbruch: fehlt die Me-Karte, ist das kein
    // Fehlerzustand, sondern schlicht `nil`.
    let req = CNContactFetchRequest(keysToFetch: [CNContactIdentifierKey as CNKeyDescriptor])
    req.unifyResults = false
    return try? store.unifiedMeContactWithKeys(
        toFetch: [CNContactIdentifierKey as CNKeyDescriptor]).identifier
}

func fetchRaw(identifier: String) throws -> CNContact? {
    let req = CNContactFetchRequest(keysToFetch: fetchKeys)
    req.unifyResults = false          // Rohdatensatz, nie unified als Schreibziel
    req.mutableObjects = false
    req.predicate = CNContact.predicateForContacts(withIdentifiers: [identifier])
    var found: CNContact?
    try store.enumerateContacts(with: req) { c, stop in found = c; stop.pointee = true }
    return found
}

// ── Leseoperationen ──────────────────────────────────────────────────────────
func opAuthorizationStatus(_ id: Any) {
    ok(id, ["authorizationStatus": authStatusText()])
}

/// Ausdrückliche Autorisierungsanforderung. Produktiv **nur** auf
/// Nutzeraktion: der Aufrufer muss `{"request": true}` senden. Es gibt kein
/// Env-Gate und keinen impliziten Weg (08 §4, Plan §8).
func opRequestAuthorization(_ id: Any, _ payload: [String: Any]) {
    guard let requested = payload["request"] as? Bool, requested else {
        fail(id, .invalidRequest,
             "requestAuthorization verlangt payload.request=true (ausdrueckliche Nutzeraktion)")
        return
    }
    switch CNContactStore.authorizationStatus(for: .contacts) {
    case .authorized:
        ok(id, ["granted": true, "authorizationStatus": "authorized",
                "promptAttempted": false])
        return
    case .denied, .restricted:
        ok(id, ["granted": false, "authorizationStatus": authStatusText(),
                "promptAttempted": false])
        return
    case .notDetermined:
        break
    @unknown default:
        fail(id, .internalError, "unbekannter Autorisierungsstatus")
        return
    }
    let sem = DispatchSemaphore(value: 0)
    var granted = false
    var reqError: NSError?
    store.requestAccess(for: .contacts) { g, e in
        granted = g; reqError = e as NSError?; sem.signal()
    }
    if sem.wait(timeout: .now() + 120) == .timedOut {
        fail(id, .internalError, "Timeout bei der Autorisierungsentscheidung",
             retryable: true)
        return
    }
    if let e = reqError {
        fail(id, .providerError, "requestAccess: \(e.domain)/\(e.code)")
        return
    }
    ok(id, ["granted": granted, "authorizationStatus": authStatusText(),
            "promptAttempted": true])
}

func opContainers(_ id: Any) {
    guard requireAuth(id) else { return }
    do {
        let cs = try store.containers(matching: nil)
        ok(id, ["containers": cs.map { c -> [String: Any] in
            let type: String
            switch c.type {
            case .local: type = "local"
            case .exchange: type = "exchange"
            case .cardDAV: type = "cardDAV"
            case .unassigned: type = "unassigned"
            @unknown default: type = "unknown"
            }
            return ["identifier": c.identifier, "name": c.name, "type": type]
        }, "keySetVersion": kKeySetVersion])
    } catch let e as NSError {
        fail(id, .providerError, "containers: \(e.domain)/\(e.code)")
    }
}

/// Streamt DTOs und schließt mit `complete:true` ab.
/// Eine ohne Abschlussmarker beendete Enumeration ist ungültig und darf im
/// Kern **niemals** als Löschmenge interpretiert werden (Plan §6.1).
func opEnumerate(_ id: Any, _ payload: [String: Any]) {
    guard requireAuth(id) else { return }
    let req = CNContactFetchRequest(keysToFetch: fetchKeys)
    req.unifyResults = false
    if let container = payload["containerIdentifier"] as? String {
        req.predicate = CNContact.predicateForContactsInContainer(withIdentifier: container)
    }
    let me = meCardIdentifier()
    var count = 0
    do {
        try store.enumerateContacts(with: req) { c, _ in
            emit(["protocolVersion": kProtocolVersion, "requestId": id,
                  "stream": "item", "item": dto(c, meIdentifier: me)])
            count += 1
        }
        ok(id, ["count": count, "complete": true, "keySetVersion": kKeySetVersion])
    } catch let e as NSError {
        diag("enumerate abgebrochen nach \(count) Datensaetzen")
        fail(id, .providerError, "enumerate: \(e.domain)/\(e.code)")
    }
}

func opChanges(_ id: Any, _ payload: [String: Any]) {
    guard requireAuth(id) else { return }
    let req = CNChangeHistoryFetchRequest()
    req.shouldUnifyResults = false
    req.includeGroupChanges = false
    req.excludedTransactionAuthors = [kTransactionAuthor]   // Echo-Unterdrückung
    if let tokenB64 = payload["startingToken"] as? String {
        guard let t = Data(base64Encoded: tokenB64) else {
            fail(id, .invalidToken, "startingToken ist kein gueltiges Base64")
            return
        }
        req.startingToken = t
    }
    do {
        let res = try JCChangeHistoryShim.changeHistoryEnumerator(for: store, request: req)
        var events: [[String: Any]] = []
        while let ev = res.value.nextObject() as? CNChangeHistoryEvent {
            switch ev {
            case let e as CNChangeHistoryAddContactEvent:
                events.append(["type": "add", "providerIdentifier": e.contact.identifier,
                               "containerIdentifier": jn(e.containerIdentifier)])
            case let e as CNChangeHistoryUpdateContactEvent:
                events.append(["type": "update", "providerIdentifier": e.contact.identifier])
            case let e as CNChangeHistoryDeleteContactEvent:
                events.append(["type": "delete", "providerIdentifier": e.contactIdentifier])
            case is CNChangeHistoryDropEverythingEvent:
                // Legitimes Resync-Signal, kein Fehler (Plan §6.2).
                events.append(["type": "dropEverything"])
            default:
                events.append(["type": "other"])
            }
        }
        // Der Cursor kommt AUS DER ANTWORT — nie aus einem zweiten Store-Read
        // (deshalb existiert produktiv keine `token`-Operation, Plan §9.1).
        ok(id, ["events": events, "count": events.count,
                "currentToken": res.currentHistoryToken.base64EncodedString(),
                "keySetVersion": kKeySetVersion])
    } catch let e as NSError {
        fail(id, .providerError, "changes: \(e.domain)/\(e.code)")
    }
}

func opGet(_ id: Any, _ payload: [String: Any]) {
    guard requireAuth(id) else { return }
    guard let ident = payload["providerIdentifier"] as? String else {
        fail(id, .invalidRequest, "providerIdentifier fehlt"); return
    }
    do {
        guard let c = try fetchRaw(identifier: ident) else {
            fail(id, .notFound, "Datensatz nicht gefunden"); return
        }
        ok(id, ["contact": dto(c, meIdentifier: meCardIdentifier())])
    } catch let e as NSError {
        fail(id, e.code == CNError.recordDoesNotExist.rawValue ? .notFound : .providerError,
             "get: \(e.domain)/\(e.code)")
    }
}

/// Ausschließlich lesend. Der zurückgegebene `unifiedIdentifier` ist belegt
/// instabil und wird **nie** als Schreibziel verwendet (Plan §7.1, §9.1).
func opGetUnifiedReadOnly(_ id: Any, _ payload: [String: Any]) {
    guard requireAuth(id) else { return }
    guard let ident = payload["providerIdentifier"] as? String else {
        fail(id, .invalidRequest, "providerIdentifier fehlt"); return
    }
    do {
        let c = try store.unifiedContact(withIdentifier: ident, keysToFetch: fetchKeys)
        ok(id, ["contact": dto(c, meIdentifier: meCardIdentifier()),
                "requestedIdentifier": ident,
                "unifiedIdentifier": c.identifier,
                "identifierChanged": c.identifier != ident,
                "readOnly": true])
    } catch let e as NSError {
        fail(id, e.code == CNError.recordDoesNotExist.rawValue ? .notFound : .providerError,
             "getUnifiedReadOnly: \(e.domain)/\(e.code)")
    }
}

// ── Mutationen: vertraglich definiert, bis Gate C nicht implementiert ────────
// Die Pflichtfelder werden bereits validiert, damit der Vertrag von Anfang an
// verbindlich ist. Es findet KEIN Store-Schreibzugriff statt.
func opMutationNotImplemented(_ id: Any, _ op: String, _ payload: [String: Any]) {
    var missing: [String] = []
    for key in ["mutationId", "idempotencyKey", "approvalId"] where payload[key] == nil {
        missing.append(key)
    }
    if op != "create" && payload["targetProviderIdentifier"] == nil {
        missing.append("targetProviderIdentifier")
    }
    if !missing.isEmpty {
        fail(id, .invalidRequest,
             "Pflichtfelder fehlen: \(missing.sorted().joined(separator: ","))")
        return
    }
    fail(id, .notImplemented,
         "\(op) ist vertraglich definiert, aber bis Gate C nicht implementiert")
}

// ── Handshake ────────────────────────────────────────────────────────────────
func handshakePayload() -> [String: Any] {
    [
        "type": "ready",
        "protocolVersion": kProtocolVersion,
        "bundleIdentifier": kBundleIdentifier,
        "transactionAuthor": kTransactionAuthor,
        "keySetVersion": kKeySetVersion,
        "authorizationStatus": authStatusText(),
        "operations": ["ping", "caps", "authorizationStatus", "requestAuthorization",
                       "containers", "enumerate", "changes", "get",
                       "getUnifiedReadOnly", "create", "update", "delete",
                       "shutdown"],
        "capabilities": capabilityStates(),
    ]
}

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

    // Inkompatible Protokollversion: fail-closed ablehnen.
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
    case "containers":           opContainers(id)
    case "enumerate":            opEnumerate(id, payload)
    case "changes":              opChanges(id, payload)
    case "get":                  opGet(id, payload)
    case "getUnifiedReadOnly":   opGetUnifiedReadOnly(id, payload)
    case "create", "update", "delete":
        opMutationNotImplemented(id, op, payload)
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

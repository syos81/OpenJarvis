//  sidecar.swift — SPIKE G3a (ADR-0016). Temporär, nicht produktiv.
//
//  Dünner Kontakte-Sidecar: JSON-Lines über stdin/stdout.
//  ERLAUBT (ADR-0016 §4): CNContactStore-Zugriffe, providerneutrale DTOs,
//  technische Fehlercodes aus geschlossener Menge, deterministische Serialisierung.
//  VERBOTEN: Fachlogik, Workspaces, Rollen, Merge, Risikobewertung, Audit,
//  kanonische Speicherung, Normalisierung, Hashing.
//
//  SPIKE-SICHERHEITSRAIL (nur für den Spike, NICHT produktiv):
//  Schreib-/Löschoperationen sind hart auf Datensätze mit dem Präfix
//  ZZZ-JarvisTest- begrenzt. In Produktion entfällt dieser Rail; dort
//  entscheidet der Kern, was geschrieben wird.
//
//  stdout = ausschließlich Protokoll. Alle Diagnosen nach stderr, ohne PII.

import Foundation
import Contacts

// ── Konstanten ────────────────────────────────────────────────────────────────
let kProtocolVersion = 1
let kTransactionAuthor = "de.jarvis.contacts-spike"
let kTestPrefix = "ZZZ-JarvisTest-"

// ── Ausgabe ───────────────────────────────────────────────────────────────────
let stdoutLock = NSLock()

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(
        withJSONObject: obj, options: [.sortedKeys, .withoutEscapingSlashes]),
          let line = String(data: data, encoding: .utf8) else {
        diag("FATAL: Antwort nicht serialisierbar")
        return
    }
    stdoutLock.lock()
    FileHandle.standardOutput.write((line + "\n").data(using: .utf8)!)
    stdoutLock.unlock()
}

/// Diagnose nach stderr. Niemals PII (keine Namen, E-Mails, Nummern, IDs).
func diag(_ s: String) {
    FileHandle.standardError.write(("[sidecar] " + s + "\n").data(using: .utf8)!)
}

func ok(_ id: Any, _ result: [String: Any]) {
    emit(["id": id, "ok": true, "result": result])
}

/// Geschlossene Fehlermenge (Mapping auf CapabilityError erfolgt im Kern).
enum ErrCode: String {
    case tccDenied      = "tcc_denied"
    case notFound       = "not_found"
    case conflict       = "conflict"
    case invalidRequest = "invalid_request"
    case forbidden      = "forbidden"
    case providerError  = "provider_error"
    case unsupported    = "unsupported"
    case internalError  = "internal"
    // SPIKE-ONLY: env-gatete Operation wurde ohne gesetztes Gate angefragt.
    case operationDisabled = "operation_disabled"
}

func fail(_ id: Any, _ code: ErrCode, _ message: String, retryable: Bool = false) {
    emit(["id": id, "ok": false,
          "error": ["code": code.rawValue, "message": message, "retryable": retryable]])
}

// ── Store ─────────────────────────────────────────────────────────────────────
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

// ── SPIKE-ONLY: ausdrückliche Autorisierungsanforderung (G7) ──────────────────
// Belegter Plattformbefund (Live-Test 2026-07-27, macOS 12.7.6): Eine normale
// Store-Operation wie `containers` löst bei `notDetermined` KEINEN TCC-Dialog
// aus — sie scheitert am `requireAuth`-Gate mit `tcc_denied`. Der Dialog
// entsteht ausschließlich durch einen ausdrücklichen
// `CNContactStore.requestAccess(for:)`-Aufruf.
//
// Diese Operation ist eine Spike-Erweiterung und KEINE produktive
// Protokollentscheidung. Sie ist standardmäßig deaktiviert und nur verfügbar,
// wenn der Prozess mit JARVIS_CONTACTS_SPIKE_TCC=1 gestartet wurde.
let kTccGateEnv = "JARVIS_CONTACTS_SPIKE_TCC"
let kRequestAuthTimeout: TimeInterval = 120   // fester Timeout, fail-closed

func tccGateEnabled() -> Bool {
    ProcessInfo.processInfo.environment[kTccGateEnv] == "1"
}

/// Fordert die Kontakte-Autorisierung genau einmal an. Führt NIEMALS eine
/// Store-Operation aus: keine Kontakte, Container, Gruppen, Change History,
/// kein CRUD. Bestätigt keinen Dialog automatisch und prompt bei `denied`
/// oder `restricted` nicht erneut.
func opRequestAuthorization(_ id: Any) {
    guard tccGateEnabled() else {
        fail(id, .operationDisabled,
             "requestAuthorization ist deaktiviert (\(kTccGateEnv)=1 erforderlich)")
        return
    }
    switch CNContactStore.authorizationStatus(for: .contacts) {
    case .authorized:
        // Kein Dialog, kein Store-Read.
        ok(id, ["granted": true, "authorizationStatus": "authorized",
                "promptAttempted": false])
        return
    case .denied, .restricted:
        // Kein erneuter Prompt — die Entscheidung liegt beim Nutzer im System.
        ok(id, ["granted": false, "authorizationStatus": authStatusText(),
                "promptAttempted": false])
        return
    case .notDetermined:
        break
    @unknown default:
        fail(id, .internalError, "unbekannter Autorisierungsstatus")
        return
    }

    diag("requestAccess wird genau einmal angefordert (Timeout \(Int(kRequestAuthTimeout)) s)")
    let sem = DispatchSemaphore(value: 0)
    var granted = false
    var reqError: NSError?
    store.requestAccess(for: .contacts) { g, e in
        granted = g
        reqError = e as NSError?
        sem.signal()
    }
    if sem.wait(timeout: .now() + kRequestAuthTimeout) == .timedOut {
        fail(id, .internalError,
             "Timeout beim Warten auf die Autorisierungsentscheidung", retryable: true)
        return
    }
    if let e = reqError {
        fail(id, .providerError, "requestAccess: \(e.domain)/\(e.code)")
        return
    }
    let after = authStatusText()
    diag("Autorisierungsentscheidung erhalten, Status \(after)")
    ok(id, ["granted": granted, "authorizationStatus": after, "promptAttempted": true])
}

// ── Schlüsselsatz (versioniert; Änderung erzwingt Resync) ─────────────────────
let kKeySetVersion = 1
let fetchKeys: [CNKeyDescriptor] = [
    CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey,
    CNContactMiddleNameKey, CNContactNamePrefixKey, CNContactNameSuffixKey,
    CNContactNicknameKey, CNContactOrganizationNameKey, CNContactJobTitleKey,
    CNContactDepartmentNameKey, CNContactBirthdayKey,
    CNContactEmailAddressesKey, CNContactPhoneNumbersKey, CNContactPostalAddressesKey,
    CNContactThumbnailImageDataKey, CNContactTypeKey,
].map { $0 as CNKeyDescriptor }

// ── DTO: deterministische, providerneutrale Serialisierung ────────────────────
// Sortierte Schlüssel, explizite Nullwerte, keine locale-abhängige Formatierung.
// KEIN Hashing, KEINE Normalisierung — das ist Kernaufgabe.
/// JSON-tauglicher Wert oder explizites null (nie stillschweigend weglassen).
func jn(_ v: Any?) -> Any { v ?? NSNull() }

func dto(_ c: CNContact) -> [String: Any] {
    let emails: [[String: Any]] = c.emailAddresses.map {
        ["label": jn($0.label), "value": $0.value as String]
    }
    let phones: [[String: Any]] = c.phoneNumbers.map {
        ["label": jn($0.label), "value": $0.value.stringValue]
    }
    let addresses: [[String: Any]] = c.postalAddresses.map { lv in
        let a = lv.value
        return ["label": jn(lv.label), "street": a.street, "city": a.city,
                "state": a.state, "postalCode": a.postalCode, "country": a.country,
                "isoCountryCode": a.isoCountryCode]
    }
    var d: [String: Any] = [
        "keySetVersion": kKeySetVersion,
        "identifier": c.identifier,
        "contactType": c.contactType == .organization ? "organization" : "person",
        "givenName": c.givenName, "familyName": c.familyName,
        "middleName": c.middleName, "namePrefix": c.namePrefix,
        "nameSuffix": c.nameSuffix, "nickname": c.nickname,
        "organizationName": c.organizationName, "jobTitle": c.jobTitle,
        "departmentName": c.departmentName,
        "emails": emails, "phones": phones, "postalAddresses": addresses,
        "hasThumbnail": c.imageDataAvailable,
    ]
    if let b = c.birthday {
        let bd: [String: Any] = ["year": jn(b.year), "month": jn(b.month), "day": jn(b.day)]
        d["birthday"] = bd
    } else {
        d["birthday"] = NSNull()
    }
    if let t = c.thumbnailImageData {
        d["thumbnailBase64"] = t.base64EncodedString()
        d["thumbnailBytes"] = t.count
    } else {
        d["thumbnailBase64"] = NSNull()
        d["thumbnailBytes"] = 0
    }
    return d
}

/// Spike-Rail: nur eindeutig markierte Testdatensätze dürfen mutiert werden.
func isTestRecord(_ c: CNContact) -> Bool {
    c.givenName.hasPrefix(kTestPrefix) || c.familyName.hasPrefix(kTestPrefix)
        || c.organizationName.hasPrefix(kTestPrefix)
}

func fetchRaw(identifier: String) throws -> CNContact? {
    let req = CNContactFetchRequest(keysToFetch: fetchKeys)
    req.unifyResults = false                       // Roh-Datensatz, siehe Schlüsselstrategie
    req.mutableObjects = true
    req.predicate = CNContact.predicateForContacts(withIdentifiers: [identifier])
    var found: CNContact?
    try store.enumerateContacts(with: req) { c, stop in found = c; stop.pointee = true }
    return found
}

// ── Operationen ───────────────────────────────────────────────────────────────
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
        }])
    } catch let e as NSError {
        fail(id, .providerError, "containers: \(e.domain)/\(e.code)")
    }
}

/// Streamt Datensätze; schließt mit complete:true ab.
/// Eine ohne complete:true abgebrochene Enumeration ist ungültig und darf
/// im Kern NIEMALS als Löschmenge interpretiert werden.
func opEnumerate(_ id: Any) {
    guard requireAuth(id) else { return }
    let req = CNContactFetchRequest(keysToFetch: fetchKeys)
    req.unifyResults = false
    var count = 0
    do {
        try store.enumerateContacts(with: req) { c, _ in
            emit(["id": id, "stream": "item", "item": dto(c)])
            count += 1
        }
        ok(id, ["count": count, "complete": true, "keySetVersion": kKeySetVersion])
    } catch let e as NSError {
        diag("enumerate abgebrochen nach \(count) Datensätzen")
        fail(id, .providerError, "enumerate: \(e.domain)/\(e.code)")
    }
}

func opChanges(_ id: Any, _ params: [String: Any]) {
    guard requireAuth(id) else { return }
    let req = CNChangeHistoryFetchRequest()
    req.shouldUnifyResults = false
    req.includeGroupChanges = false
    req.excludedTransactionAuthors = [kTransactionAuthor]   // Echo-Unterdrückung
    if let tokenB64 = params["startingToken"] as? String {
        guard let t = Data(base64Encoded: tokenB64) else {
            fail(id, .invalidRequest, "startingToken ist kein gültiges Base64"); return
        }
        req.startingToken = t
    }
    do {
        let res = try JCChangeHistoryShim.changeHistoryEnumerator(for: store, request: req)
        var events: [[String: Any]] = []
        while let ev = res.value.nextObject() as? CNChangeHistoryEvent {
            switch ev {
            case let e as CNChangeHistoryAddContactEvent:
                events.append(["type": "add", "identifier": e.contact.identifier,
                               "containerIdentifier": e.containerIdentifier ?? NSNull()])
            case let e as CNChangeHistoryUpdateContactEvent:
                // Kein containerIdentifier verfügbar (CNChangeHistoryEvent.h)
                events.append(["type": "update", "identifier": e.contact.identifier])
            case let e as CNChangeHistoryDeleteContactEvent:
                events.append(["type": "delete", "identifier": e.contactIdentifier])
            case is CNChangeHistoryDropEverythingEvent:
                events.append(["type": "dropEverything"])
            default:
                events.append(["type": "other"])
            }
        }
        ok(id, ["events": events, "count": events.count,
                "currentToken": res.currentHistoryToken.base64EncodedString()])
    } catch let e as NSError {
        fail(id, .providerError, "changes: \(e.domain)/\(e.code)")
    }
}

func opToken(_ id: Any) {
    guard requireAuth(id) else { return }
    if let t = store.currentHistoryToken {
        ok(id, ["currentToken": t.base64EncodedString(), "bytes": t.count])
    } else {
        fail(id, .unsupported, "currentHistoryToken nicht verfügbar")
    }
}

func opGet(_ id: Any, _ params: [String: Any], unified: Bool) {
    guard requireAuth(id) else { return }
    guard let ident = params["identifier"] as? String else {
        fail(id, .invalidRequest, "identifier fehlt"); return
    }
    do {
        if unified {
            let c = try store.unifiedContact(withIdentifier: ident, keysToFetch: fetchKeys)
            ok(id, ["contact": dto(c), "requestedIdentifier": ident,
                    "returnedIdentifier": c.identifier,
                    "identifierChanged": c.identifier != ident])
        } else {
            guard let c = try fetchRaw(identifier: ident) else {
                fail(id, .notFound, "Datensatz nicht gefunden"); return
            }
            ok(id, ["contact": dto(c)])
        }
    } catch let e as NSError {
        fail(id, e.code == CNError.recordDoesNotExist.rawValue ? .notFound : .providerError,
             "get: \(e.domain)/\(e.code)")
    }
}

func opCreate(_ id: Any, _ params: [String: Any]) {
    guard requireAuth(id) else { return }
    guard let given = params["givenName"] as? String,
          let family = params["familyName"] as? String else {
        fail(id, .invalidRequest, "givenName/familyName fehlen"); return
    }
    guard given.hasPrefix(kTestPrefix) || family.hasPrefix(kTestPrefix) else {
        fail(id, .forbidden, "Spike-Rail: nur \(kTestPrefix)-Datensätze"); return
    }
    let c = CNMutableContact()
    c.givenName = given
    c.familyName = family
    if let org = params["organizationName"] as? String { c.organizationName = org }
    if let jt = params["jobTitle"] as? String { c.jobTitle = jt }
    if let dep = params["departmentName"] as? String { c.departmentName = dep }
    if let emails = params["emails"] as? [[String: String]] {
        c.emailAddresses = emails.compactMap {
            guard let v = $0["value"] else { return nil }
            return CNLabeledValue(label: $0["label"], value: v as NSString)
        }
    }
    if let phones = params["phones"] as? [[String: String]] {
        c.phoneNumbers = phones.compactMap {
            guard let v = $0["value"] else { return nil }
            return CNLabeledValue(label: $0["label"], value: CNPhoneNumber(stringValue: v))
        }
    }
    if let addrs = params["postalAddresses"] as? [[String: String]] {
        c.postalAddresses = addrs.map { a in
            let p = CNMutablePostalAddress()
            p.street = a["street"] ?? ""; p.city = a["city"] ?? ""
            p.state = a["state"] ?? ""; p.postalCode = a["postalCode"] ?? ""
            p.country = a["country"] ?? ""; p.isoCountryCode = a["isoCountryCode"] ?? ""
            return CNLabeledValue(label: a["label"], value: p)
        }
    }
    if let b = params["birthday"] as? [String: Int] {
        var dc = DateComponents()
        dc.year = b["year"]; dc.month = b["month"]; dc.day = b["day"]
        c.birthday = dc
    }
    if let noteText = params["note"] as? String { c.note = noteText }

    let req = CNSaveRequest()
    req.transactionAuthor = kTransactionAuthor
    req.add(c, toContainerWithIdentifier: params["containerIdentifier"] as? String)
    do {
        try store.execute(req)
        ok(id, ["identifier": c.identifier, "verified": (try? fetchRaw(identifier: c.identifier)) != nil])
    } catch let e as NSError {
        fail(id, .providerError, "create: \(e.domain)/\(e.code) \(e.localizedDescription)")
    }
}

func opUpdate(_ id: Any, _ params: [String: Any], viaUnified: Bool) {
    guard requireAuth(id) else { return }
    guard let ident = params["identifier"] as? String else {
        fail(id, .invalidRequest, "identifier fehlt"); return
    }
    do {
        let base: CNContact?
        if viaUnified {
            base = try store.unifiedContact(withIdentifier: ident, keysToFetch: fetchKeys)
        } else {
            base = try fetchRaw(identifier: ident)
        }
        guard let existing = base else { fail(id, .notFound, "nicht gefunden"); return }
        guard isTestRecord(existing) else {
            fail(id, .forbidden, "Spike-Rail: nur \(kTestPrefix)-Datensätze"); return
        }
        guard let m = existing.mutableCopy() as? CNMutableContact else {
            fail(id, .internalError, "mutableCopy fehlgeschlagen"); return
        }
        if let jt = params["jobTitle"] as? String { m.jobTitle = jt }
        if let nn = params["nickname"] as? String { m.nickname = nn }
        if let dep = params["departmentName"] as? String { m.departmentName = dep }

        let req = CNSaveRequest()
        req.transactionAuthor = kTransactionAuthor
        req.update(m)
        try store.execute(req)
        let after = try fetchRaw(identifier: m.identifier)
        ok(id, ["identifier": m.identifier, "viaUnified": viaUnified,
                "verified": after != nil,
                "readBack": after.map { dto($0) } ?? NSNull()])
    } catch let e as NSError {
        fail(id, .providerError, "update: \(e.domain)/\(e.code) \(e.localizedDescription)")
    }
}

func opDelete(_ id: Any, _ params: [String: Any]) {
    guard requireAuth(id) else { return }
    guard let ident = params["identifier"] as? String else {
        fail(id, .invalidRequest, "identifier fehlt"); return
    }
    do {
        guard let existing = try fetchRaw(identifier: ident) else {
            fail(id, .notFound, "nicht gefunden"); return
        }
        guard isTestRecord(existing) else {
            fail(id, .forbidden, "Spike-Rail: nur \(kTestPrefix)-Datensätze"); return
        }
        guard let m = existing.mutableCopy() as? CNMutableContact else {
            fail(id, .internalError, "mutableCopy fehlgeschlagen"); return
        }
        let snapshot = dto(existing)
        let req = CNSaveRequest()
        req.transactionAuthor = kTransactionAuthor
        req.delete(m)
        try store.execute(req)
        let after = try fetchRaw(identifier: ident)
        ok(id, ["identifier": ident, "deleted": after == nil, "snapshot": snapshot])
    } catch let e as NSError {
        fail(id, .providerError, "delete: \(e.domain)/\(e.code) \(e.localizedDescription)")
    }
}

// ── Handshake ─────────────────────────────────────────────────────────────────
emit([
    "type": "ready", "protocol": kProtocolVersion,
    "authorizationStatus": authStatusText(),
    "keySetVersion": kKeySetVersion,
    "transactionAuthor": kTransactionAuthor,
    "caps": ["ping", "caps", "containers", "enumerate", "changes", "token",
             "get", "getUnified", "create", "update", "updateViaUnified",
             "delete", "requestAuthorization", "shutdown"],
    "limits": ["mutationsRestrictedToPrefix": kTestPrefix,
               "linkUnlinkSupported": false],   // CNSaveRequest hat keine Link-API
    // SPIKE-ONLY: Verfügbarkeit der ausdrücklichen Autorisierungsanforderung.
    "requestAuthorizationSupported": true,
    "requestAuthorizationEnabled": tccGateEnabled(),
])
diag("bereit, Protokollversion \(kProtocolVersion), Autorisierung \(authStatusText())")

// ── Hauptschleife: eine JSON-Zeile je Anfrage ─────────────────────────────────
while let line = readLine(strippingNewline: true) {
    let trimmed = line.trimmingCharacters(in: .whitespaces)
    if trimmed.isEmpty { continue }
    guard let data = trimmed.data(using: .utf8),
          let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        emit(["id": NSNull(), "ok": false,
              "error": ["code": ErrCode.invalidRequest.rawValue,
                        "message": "Zeile ist kein JSON-Objekt", "retryable": false]])
        continue
    }
    let id = obj["id"] ?? NSNull()
    guard let op = obj["op"] as? String else {
        fail(id, .invalidRequest, "op fehlt"); continue
    }
    let params = obj["params"] as? [String: Any] ?? [:]

    switch op {
    case "ping":             ok(id, ["pong": true])
    case "caps":             ok(id, ["protocol": kProtocolVersion,
                                     "authorizationStatus": authStatusText(),
                                     "keySetVersion": kKeySetVersion,
                                     "linkUnlinkSupported": false,
                                     // SPIKE-ONLY (siehe opRequestAuthorization)
                                     "requestAuthorizationSupported": true,
                                     "requestAuthorizationEnabled": tccGateEnabled()])
    case "containers":       opContainers(id)
    case "enumerate":        opEnumerate(id)
    case "changes":          opChanges(id, params)
    case "token":            opToken(id)
    case "get":              opGet(id, params, unified: false)
    case "getUnified":       opGet(id, params, unified: true)
    case "create":           opCreate(id, params)
    case "update":           opUpdate(id, params, viaUnified: false)
    case "updateViaUnified": opUpdate(id, params, viaUnified: true)
    case "delete":           opDelete(id, params)
    // SPIKE-ONLY, env-gatet über JARVIS_CONTACTS_SPIKE_TCC=1
    case "requestAuthorization": opRequestAuthorization(id)
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

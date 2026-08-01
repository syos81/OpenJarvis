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
// Vertragsversionen der Mutationshuelle und des Feldvertrags (ADR-0019 §6).
// Beide Seiten nennen sie; Ungleichheit ist fail-closed.
let kMutationContractVersion = 1
let kFieldContractVersion = 1

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

func fail(_ id: Any, _ code: ErrCode, _ message: String, retryable: Bool = false,
          providerDomain: String? = nil, providerCode: Int? = nil) {
    // `providerDomain`/`providerCode` tragen die Apple-Fehlerangabe STRUKTURIERT.
    // Frueher steckte sie nur im Fliesstext der Meldung und ging beim ersten
    // Weiterreichen verloren — die Oberflaeche zeigte dann nur noch einen
    // Ausnahmeklassennamen, und die eigentliche Diagnose war weg.
    //
    // Bewusst NUR Domain und numerischer Code: `localizedDescription` kann
    // Pfade und andere private Angaben enthalten und wird nie uebertragen.
    var error: [String: Any] = ["code": code.rawValue, "message": message,
                                "retryable": retryable]
    if let d = providerDomain { error["providerDomain"] = d }
    if let c = providerCode   { error["providerCode"] = c }
    emit(["protocolVersion": kProtocolVersion, "requestId": id, "ok": false,
          "error": error])
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
        // Einzeln je Operation, nie pauschal: `create` ist implementiert,
        // `update` und `delete` bleiben not_implemented (ADR-0019 §9).
        // Ein pauschales Flag haette Update und Delete mitfreigeschaltet.
        "createImplemented": true,
        "updateImplemented": false,
        "deleteImplemented": false,
        "mutationsImplemented": true,    // mindestens eine Operation schreibt
        "mutationContractVersion": kMutationContractVersion,
        "fieldContractVersion": kFieldContractVersion,
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
        // Der Nutzer hat den Dialog nicht beantwortet — oder es erschien
        // keiner. Beides ist wiederholbar, beides ist KEIN Providerfehler.
        fail(id, .internalError, "Die Autorisierungsentscheidung blieb aus.",
             retryable: true, providerDomain: "timeout", providerCode: 0)
        return
    }
    if let e = reqError {
        // Nur Domain und numerischer Code. Der Text bleibt generisch.
        fail(id, .providerError,
             "requestAccess wurde vom System abgelehnt.",
             providerDomain: e.domain, providerCode: e.code)
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

// ── Mutationen: vertraglich definiert, noch nicht implementiert ──────────────
// Die Pflichtfelder werden bereits validiert, damit der Vertrag von Anfang an
// verbindlich ist. Es findet KEIN Store-Schreibzugriff statt.
//
// Gilt weiterhin fuer `update` und `delete` (ADR-0019 §9: erst M4 bzw. M5;
// Delete zusaetzlich hinter DEC-D06).
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
         "\(op) ist vertraglich definiert, aber nicht implementiert")
}

// ═════════════════════════════════════════════════════════════════════════════
// CREATE — der einzige implementierte Schreibpfad (ADR-0019)
// ═════════════════════════════════════════════════════════════════════════════
//
// Die Antwort ist IMMER ok:true mit genau einem von drei Ausgaengen. Das ist
// Absicht: ein `fail()` liesse offen, ob vor oder nach der Uebergabe an den
// Store abgebrochen wurde — und genau diese Unterscheidung ist die
// sicherheitsrelevante Aussage des ganzen Pfades.
//
//   applied          Save bestaetigt UND derselbe Datensatz zurueckgelesen.
//   not_sent         Nachweislich kein SaveRequest uebergeben. Alles Pruefbare
//                    geschieht deshalb VOR `store.execute`.
//   outcome_unknown  Ab dem Moment der Uebergabe. Ein Wurf aus `execute` zaehlt
//                    dazu: der Store hat den Request bereits, und welche Fehler
//                    dort vor und welche nach dem Commit entstehen, ist
//                    Apple-Interna und nicht beweisbar.
//
// KEIN automatischer Retry, KEINE Schleife, KEINE Namenssuche, KEINE Domaenen-
// oder Freigabeentscheidung. Der Sidecar bleibt duenn: er validiert den
// Feldvertrag, baut das CN-Objekt, speichert einmal, liest zurueck.
//
// Der Read-back-DIGEST entsteht bewusst NICHT hier, sondern im Kern: seine
// Bildung verlangt die Ruecknormalisierung der Apple-Rohlabels, und
// Normalisierung ist Kernaufgabe (ADR-0016 Punkt 4). Der Sidecar liefert den
// zurueckgelesenen Datensatz als DTO; den Beleg bildet der Kern daraus.


/// Prozesslokale Wiederholungssperre.
///
/// Sie hilft gegen einen doppelten Aufruf INNERHALB derselben Sidecar-Laufzeit
/// und ist ausdruecklich KEINE Exactly-once-Garantie: mit dem Prozess stirbt
/// sie. Die belastbare Zusage „hoechstens ein Send je Mutation" erbringt allein
/// der Kern (Outbox-Claim, verbrauchte Freigabe, terminale Zustaende).
var mutationMemo: [String: [String: Any]] = [:]
let mutationMemoLock = NSLock()

func mutationResult(_ outcome: String, errorCode: String? = nil,
                    extra: [String: Any] = [:]) -> [String: Any] {
    var r: [String: Any] = [
        "outcome": outcome,
        "mutationContractVersion": kMutationContractVersion,
        "fieldContractVersion": kFieldContractVersion,
        "transactionAuthor": kTransactionAuthor,
    ]
    if let c = errorCode { r["errorCode"] = c }
    for (k, v) in extra { r[k] = v }
    return r
}

/// Geschlossener Labelvorrat des Feldvertrags v1 → Apple-Konstanten.
/// Ein unbekanntes Label erreicht diese Stelle nicht (der Kern prueft) — und
/// wird hier erneut abgewiesen: es gaebe sonst ein Label, dessen Rueckweg beim
/// Lesen nicht belegt ist.
let kEmailLabels: [String: String] = [
    "home": CNLabelHome, "work": CNLabelWork, "other": CNLabelOther]
let kPhoneLabels: [String: String] = [
    "home": CNLabelHome, "work": CNLabelWork, "other": CNLabelOther,
    "mobile": CNLabelPhoneNumberMobile, "main": CNLabelPhoneNumberMain]
let kAddressLabels: [String: String] = [
    "home": CNLabelHome, "work": CNLabelWork, "other": CNLabelOther]
let kUrlLabels: [String: String] = [
    "home": CNLabelHome, "work": CNLabelWork, "other": CNLabelOther]
let kDateLabels: [String: String] = ["other": CNLabelOther]

/// Verletzung des Feldvertrags. Traegt ausschliesslich eine technische
/// Meldung — nie einen Feldwert, denn der waere PII.
struct FieldContractViolation: Error { let message: String }

func cnLabel(_ raw: Any?, _ allowed: [String: String]) throws -> String? {
    if raw == nil || raw is NSNull { return nil }
    guard let s = raw as? String else {
        throw FieldContractViolation(message: "Label muss Text sein")
    }
    guard let mapped = allowed[s] else {
        throw FieldContractViolation(message: "unbekanntes Label")
    }
    return mapped
}

/// Baut das CN-Objekt streng aus dem Feldvertrag v1.
/// Was der Vertrag nicht kennt, wird nicht gesetzt — es gibt keinen Zweig,
/// ueber den Notiz, Bild, Beziehung, soziales Profil oder Gruppe hineinkaeme.
func buildMutableContact(_ f: [String: Any]) throws -> CNMutableContact {
    let c = CNMutableContact()

    if let art = f["contactType"] as? String {
        switch art {
        case "person":       c.contactType = .person
        case "organization": c.contactType = .organization
        default: throw FieldContractViolation(message: "contactType unzulaessig")
        }
    }

    let scalars: [(String, ReferenceWritableKeyPath<CNMutableContact, String>)] = [
        ("givenName", \.givenName), ("middleName", \.middleName),
        ("familyName", \.familyName), ("previousFamilyName", \.previousFamilyName),
        ("namePrefix", \.namePrefix), ("nameSuffix", \.nameSuffix),
        ("nickname", \.nickname), ("phoneticGivenName", \.phoneticGivenName),
        ("phoneticFamilyName", \.phoneticFamilyName),
        ("organizationName", \.organizationName),
        ("departmentName", \.departmentName), ("jobTitle", \.jobTitle),
    ]
    for (key, path) in scalars {
        guard let raw = f[key], !(raw is NSNull) else { continue }
        guard let s = raw as? String else {
            throw FieldContractViolation(message: "\(key): Text erwartet")
        }
        c[keyPath: path] = s
    }

    if let b = f["birthday"] as? [String: Any] {
        guard let m = b["month"] as? Int, let d = b["day"] as? Int else {
            throw FieldContractViolation(
                message: "birthday: Monat und Tag erforderlich")
        }
        var comps = DateComponents()
        comps.month = m
        comps.day = d
        if let y = b["year"] as? Int { comps.year = y }
        c.birthday = comps
    }

    func labeledStrings(_ key: String,
                        _ allowed: [String: String]) throws -> [CNLabeledValue<NSString>] {
        guard let items = f[key] as? [[String: Any]] else { return [] }
        var out: [CNLabeledValue<NSString>] = []
        for i in items {
            guard let v = i["value"] as? String, !v.isEmpty else {
                throw FieldContractViolation(message: "\(key): leerer Wert")
            }
            let l = try cnLabel(i["label"], allowed)
            out.append(CNLabeledValue(label: l, value: v as NSString))
        }
        return out
    }

    c.emailAddresses = try labeledStrings("emails", kEmailLabels)
    c.urlAddresses = try labeledStrings("urls", kUrlLabels)

    if let items = f["phones"] as? [[String: Any]] {
        var out: [CNLabeledValue<CNPhoneNumber>] = []
        for i in items {
            guard let v = i["value"] as? String, !v.isEmpty else {
                throw FieldContractViolation(message: "phones: leerer Wert")
            }
            let l = try cnLabel(i["label"], kPhoneLabels)
            out.append(CNLabeledValue(label: l, value: CNPhoneNumber(stringValue: v)))
        }
        c.phoneNumbers = out
    }

    if let items = f["postalAddresses"] as? [[String: Any]] {
        var out: [CNLabeledValue<CNPostalAddress>] = []
        for i in items {
            let a = CNMutablePostalAddress()
            a.street = (i["street"] as? String) ?? ""
            a.city = (i["city"] as? String) ?? ""
            a.state = (i["state"] as? String) ?? ""
            a.postalCode = (i["postalCode"] as? String) ?? ""
            a.country = (i["country"] as? String) ?? ""
            a.isoCountryCode = (i["isoCountryCode"] as? String) ?? ""
            out.append(CNLabeledValue(label: try cnLabel(i["label"], kAddressLabels),
                                      value: a))
        }
        c.postalAddresses = out
    }

    if let items = f["dates"] as? [[String: Any]] {
        var out: [CNLabeledValue<NSDateComponents>] = []
        for i in items {
            guard let m = i["month"] as? Int, let d = i["day"] as? Int else {
                throw FieldContractViolation(
                    message: "dates: Monat und Tag erforderlich")
            }
            let comps = NSDateComponents()
            comps.month = m
            comps.day = d
            if let y = i["year"] as? Int { comps.year = y }
            out.append(CNLabeledValue(label: try cnLabel(i["label"], kDateLabels),
                                      value: comps))
        }
        c.dates = out
    }

    return c
}

func opCreate(_ id: Any, _ payload: [String: Any]) {
    // ── Phase 1: alles Pruefbare VOR jeder Uebergabe an den Store ───────────
    func notSent(_ code: String, _ message: String) {
        diag("create not_sent: \(code) — \(message)")
        ok(id, mutationResult("not_sent", errorCode: code))
    }

    var missing: [String] = []
    for key in ["mutationId", "idempotencyKey", "approvalId", "containerIdentifier"]
    where payload[key] == nil {
        missing.append(key)
    }
    if !missing.isEmpty {
        notSent("invalid_request",
                "Pflichtfelder fehlen: \(missing.sorted().joined(separator: ","))")
        return
    }
    guard (payload["mutationContractVersion"] as? Int) == kMutationContractVersion,
          (payload["fieldContractVersion"] as? Int) == kFieldContractVersion else {
        notSent("protocol_mismatch",
                "Vertragsversionen passen nicht zu diesem Sidecar")
        return
    }
    guard let idem = payload["idempotencyKey"] as? String, !idem.isEmpty else {
        notSent("invalid_request", "idempotencyKey leer"); return
    }
    guard let container = payload["containerIdentifier"] as? String,
          !container.isEmpty else {
        notSent("invalid_request", "containerIdentifier leer"); return
    }
    guard let fields = payload["fields"] as? [String: Any], !fields.isEmpty else {
        notSent("invalid_request", "fields fehlt oder ist leer"); return
    }

    // Wiederholung innerhalb derselben Laufzeit: gemerktes Ergebnis, kein
    // zweiter Save. Siehe `mutationMemo` — keine Exactly-once-Zusage.
    mutationMemoLock.lock()
    let gemerkt = mutationMemo[idem]
    mutationMemoLock.unlock()
    if let g = gemerkt {
        diag("create: idempotencyKey bereits beantwortet, kein zweiter Save")
        ok(id, g)
        return
    }

    guard CNContactStore.authorizationStatus(for: .contacts) == .authorized else {
        notSent("tcc_denied", "Autorisierung ist \(authStatusText())"); return
    }

    // Der Zielcontainer wird EXAKT aufgeloest. Keine Namenssuche, keine
    // automatische Wahl, kein „erster Treffer".
    do {
        let treffer = try store.containers(
            matching: CNContainer.predicateForContainers(withIdentifiers: [container]))
        if treffer.isEmpty {
            notSent("not_found", "Zielcontainer existiert nicht"); return
        }
        if treffer.count > 1 {
            notSent("conflict", "Zielcontainer ist nicht eindeutig"); return
        }
    } catch let e as NSError {
        notSent("provider_error", "containers: \(e.domain)/\(e.code)"); return
    }

    let neu: CNMutableContact
    do {
        neu = try buildMutableContact(fields)
    } catch let v as FieldContractViolation {
        notSent("invalid_request", v.message); return
    } catch {
        notSent("invalid_request", "Feldvertrag verletzt"); return
    }
    let identifier = neu.identifier

    let req = CNSaveRequest()
    req.transactionAuthor = kTransactionAuthor   // Grundlage der Echo-Unterdrueckung
    req.add(neu, toContainerWithIdentifier: container)

    // ── Phase 2: genau eine Uebergabe. Ab hier ist nichts mehr „nicht gesendet"
    func unknown(_ code: String, _ message: String) {
        diag("create outcome_unknown: \(code) — \(message)")
        let r = mutationResult("outcome_unknown", errorCode: code)
        mutationMemoLock.lock(); mutationMemo[idem] = r; mutationMemoLock.unlock()
        ok(id, r)
    }

    do {
        try store.execute(req)
    } catch let e as NSError {
        // Bewusst KEINE Auswertung des Fehlercodes zu „nichts passiert": ob ein
        // Fehler vor oder nach dem Commit entsteht, ist nicht beweisbar. Der
        // Kern loest das ueber den Abgleich auf, nie ueber einen zweiten Send.
        unknown("save_failed", "save: \(e.domain)/\(e.code)")
        return
    }

    // ── Phase 3: Read-back. Ohne ihn gilt der Vorgang NICHT als angewandt ───
    do {
        guard let zurueck = try fetchRaw(identifier: identifier) else {
            unknown("readback_not_found",
                    "Save bestaetigt, Datensatz nicht wieder auffindbar")
            return
        }
        let r = mutationResult("applied", extra: [
            "providerIdentifier": zurueck.identifier,
            "containerIdentifier": container,
            "contact": dto(zurueck, meIdentifier: meCardIdentifier()),
        ])
        mutationMemoLock.lock(); mutationMemo[idem] = r; mutationMemoLock.unlock()
        diag("create applied")
        ok(id, r)
    } catch let e as NSError {
        unknown("readback_failed", "readback: \(e.domain)/\(e.code)")
    }
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
    case "create":               opCreate(id, payload)
    case "update", "delete":
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

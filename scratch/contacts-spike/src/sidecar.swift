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

// ── SPIKE-ONLY: Diagnose-Gate für die create-Timeout-Analyse ──────────────────
// Ohne exakt JARVIS_CONTACTS_SPIKE_DIAGNOSTICS=1 erscheint KEINE zusätzliche
// Ausgabe; das bestehende Verhalten bleibt unverändert.
//
// Ausgegeben werden ausschließlich konstante technische Stufennamen — niemals
// Namen, Identifier, E-Mail-Adressen, Telefonnummern, Anschriften, Geburtstage,
// Organisationen oder ganze Payloads. stdout bleibt reines JSON-Lines-Protokoll.
let kDiagGateEnv = "JARVIS_CONTACTS_SPIKE_DIAGNOSTICS"

func diagGateEnabled() -> Bool {
    ProcessInfo.processInfo.environment[kDiagGateEnv] == "1"
}

/// Technische Stufe nach stderr. Aufrufer übergeben ausschließlich konstante
/// Stufennamen — keine Werte aus der Anfrage.
func stage(_ name: String, error: ErrCode? = nil) {
    guard diagGateEnabled() else { return }
    if let e = error {
        diag("stage=\(name) error=\(e.rawValue)")
    } else {
        diag("stage=\(name)")
    }
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
    // BEFUND 2026-07-28: `imageDataAvailable` ist eine eigenstaendige Eigenschaft
    // mit eigenem Schluessel (CNContact.h:83 bzw. :158). Sie wurde in dto()
    // gelesen, ohne angefordert zu werden — laut CNContact.h:52 wirft das
    // CNContactPropertyNotFetchedException; in Swift fuehrt die nicht
    // abgefangene ObjC-Exception zu abort() (SIGABRT).
    CNContactImageDataAvailableKey,
    CNContactThumbnailImageDataKey, CNContactTypeKey,
].map { $0 as CNKeyDescriptor }

// ── Gestufte Keysets fuer den ausschliesslich lesenden Probe-Modus ───────────
// Stufe 1: absolutes Minimum. Stufe 2: unkritische Gruppen einzeln.
// Stufe 3: Kandidaten mit Entitlement- oder Exception-Risiko, jeweils EINZELN.
let kProbeStage1: [String] = [
    CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey,
]
let kProbeStage2: [(String, [String])] = [
    ("names-extended", [CNContactMiddleNameKey, CNContactNamePrefixKey,
                        CNContactNameSuffixKey, CNContactNicknameKey]),
    ("organization", [CNContactOrganizationNameKey, CNContactJobTitleKey,
                      CNContactDepartmentNameKey]),
    ("contact-type", [CNContactTypeKey]),
    ("emails", [CNContactEmailAddressesKey]),
    ("phones", [CNContactPhoneNumbersKey]),
    ("postal", [CNContactPostalAddressesKey]),
]
let kProbeStage3: [(String, [String])] = [
    ("image-available", [CNContactImageDataAvailableKey]),
    ("thumbnail", [CNContactThumbnailImageDataKey]),
    ("image-data", [CNContactImageDataKey]),
    ("birthday", [CNContactBirthdayKey]),
    ("dates", [CNContactDatesKey]),
    ("relations", [CNContactRelationsKey]),
    ("social-profiles", [CNContactSocialProfilesKey]),
    ("instant-messages", [CNContactInstantMessageAddressesKey]),
    ("note", [CNContactNoteKey]),        // erfordert ein Sonder-Entitlement
]

/// Symbolischer, PII-freier Stufenname eines Contact-Keys.
func symbolicKeyName(_ key: String) -> String {
    switch key {
    case CNContactIdentifierKey:              return "identifier"
    case CNContactGivenNameKey:               return "givenName"
    case CNContactFamilyNameKey:              return "familyName"
    case CNContactMiddleNameKey:              return "middleName"
    case CNContactNamePrefixKey:              return "namePrefix"
    case CNContactNameSuffixKey:              return "nameSuffix"
    case CNContactNicknameKey:                return "nickname"
    case CNContactOrganizationNameKey:        return "organizationName"
    case CNContactJobTitleKey:                return "jobTitle"
    case CNContactDepartmentNameKey:          return "departmentName"
    case CNContactTypeKey:                    return "contactType"
    case CNContactEmailAddressesKey:          return "emailAddresses"
    case CNContactPhoneNumbersKey:            return "phoneNumbers"
    case CNContactPostalAddressesKey:         return "postalAddresses"
    case CNContactImageDataAvailableKey:      return "imageDataAvailable"
    case CNContactThumbnailImageDataKey:      return "thumbnailImageData"
    case CNContactImageDataKey:               return "imageData"
    case CNContactBirthdayKey:                return "birthday"
    case CNContactDatesKey:                   return "dates"
    case CNContactRelationsKey:               return "relations"
    case CNContactSocialProfilesKey:          return "socialProfiles"
    case CNContactInstantMessageAddressesKey: return "instantMessageAddresses"
    case CNContactNoteKey:                    return "note"
    default:                                  return "unknown"
    }
}

// ── DTO: deterministische, providerneutrale Serialisierung ────────────────────
// Sortierte Schlüssel, explizite Nullwerte, keine locale-abhängige Formatierung.
// KEIN Hashing, KEINE Normalisierung — das ist Kernaufgabe.
/// JSON-tauglicher Wert oder explizites null (nie stillschweigend weglassen).
func jn(_ v: Any?) -> Any { v ?? NSNull() }

/// Liest eine Eigenschaft NUR, wenn ihr Schluessel tatsaechlich geholt wurde.
/// CNContact.h:52 verlangt genau das: sonst wirft der Zugriff
/// CNContactPropertyNotFetchedException — in Swift ein abort() (SIGABRT).
/// Nicht geholte Felder werden als explizites null ausgegeben, niemals
/// stillschweigend als Leerwert.
func ifFetched<T>(_ c: CNContact, _ key: String, _ read: (CNContact) -> T) -> T? {
    c.isKeyAvailable(key) ? read(c) : nil
}

func dto(_ c: CNContact) -> [String: Any] {
    let emails: [[String: Any]] = ifFetched(c, CNContactEmailAddressesKey) {
        $0.emailAddresses.map { ["label": jn($0.label), "value": $0.value as String] }
    } ?? []
    let phones: [[String: Any]] = ifFetched(c, CNContactPhoneNumbersKey) {
        $0.phoneNumbers.map { ["label": jn($0.label), "value": $0.value.stringValue] }
    } ?? []
    let addresses: [[String: Any]] = ifFetched(c, CNContactPostalAddressesKey) {
        $0.postalAddresses.map { lv -> [String: Any] in
            let a = lv.value
            return ["label": jn(lv.label), "street": a.street, "city": a.city,
                    "state": a.state, "postalCode": a.postalCode,
                    "country": a.country, "isoCountryCode": a.isoCountryCode]
        }
    } ?? []

    var d: [String: Any] = [
        "keySetVersion": kKeySetVersion,
        "identifier": c.identifier,          // immer vorhanden (CNContact.h:135)
        "contactType": jn(ifFetched(c, CNContactTypeKey) {
            $0.contactType == .organization ? "organization" : "person" }),
        "givenName": jn(ifFetched(c, CNContactGivenNameKey) { $0.givenName }),
        "familyName": jn(ifFetched(c, CNContactFamilyNameKey) { $0.familyName }),
        "middleName": jn(ifFetched(c, CNContactMiddleNameKey) { $0.middleName }),
        "namePrefix": jn(ifFetched(c, CNContactNamePrefixKey) { $0.namePrefix }),
        "nameSuffix": jn(ifFetched(c, CNContactNameSuffixKey) { $0.nameSuffix }),
        "nickname": jn(ifFetched(c, CNContactNicknameKey) { $0.nickname }),
        "organizationName": jn(ifFetched(c, CNContactOrganizationNameKey) {
            $0.organizationName }),
        "jobTitle": jn(ifFetched(c, CNContactJobTitleKey) { $0.jobTitle }),
        "departmentName": jn(ifFetched(c, CNContactDepartmentNameKey) {
            $0.departmentName }),
        "emails": emails, "phones": phones, "postalAddresses": addresses,
        "hasThumbnail": jn(ifFetched(c, CNContactImageDataAvailableKey) {
            $0.imageDataAvailable }),
    ]
    if let b = ifFetched(c, CNContactBirthdayKey, { $0.birthday }) ?? nil {
        d["birthday"] = ["year": jn(b.year), "month": jn(b.month),
                         "day": jn(b.day)] as [String: Any]
    } else {
        d["birthday"] = NSNull()
    }
    if let t = ifFetched(c, CNContactThumbnailImageDataKey,
                         { $0.thumbnailImageData }) ?? nil {
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
    stage("enumerate.received")
    guard requireAuth(id) else { stage("enumerate.auth_failed"); return }
    stage("enumerate.validated")
    stage("enumerate.auth_ok")
    stage("enumerate.container_resolved")     // Standardlauf: kein Container-Filter

    stage("enumerate.keys_begin")
    for k in fetchKeys.compactMap({ $0 as? String }) {
        stage("enumerate.key.\(symbolicKeyName(k))")
    }
    stage("enumerate.keys_complete")

    let req = CNContactFetchRequest(keysToFetch: fetchKeys)
    req.unifyResults = false
    stage("enumerate.request_constructed")

    var count = 0
    do {
        stage("enumerate.fetch_begin")
        try store.enumerateContacts(with: req) { c, _ in
            if count == 0 { stage("enumerate.callback_entered") }
            let item = dto(c)
            if count == 0 { stage("enumerate.serialized") }
            emit(["id": id, "stream": "item", "item": item])
            if count == 0 { stage("enumerate.response_written") }
            count += 1
        }
        stage("enumerate.fetch_returned")
        ok(id, ["count": count, "complete": true, "keySetVersion": kKeySetVersion])
        stage("enumerate.completed")
    } catch let e as NSError {
        stage("enumerate.fetch_error", error: .providerError)
        diag("enumerate abgebrochen nach \(count) Datensätzen")
        fail(id, .providerError, "enumerate: \(e.domain)/\(e.code)")
    }
}

// ── SPIKE-ONLY: PII-freie Isolationsprüfung (AUSSCHLIESSLICH LESEND) ────────
// Klassifiziert den vorhandenen Bestand, OHNE Kontaktdaten preiszugeben.
//
// Warum im Sidecar und nicht im Host: Die Klassifikation braucht Namensfelder
// (Präfixabgleich) und Identifier (Me-Card-Vergleich, Dublettenerkennung).
// Beides darf die Prozessgrenze NIEMALS überschreiten. Deshalb bleibt alles
// im Prozessspeicher; nach aussen gehen ausschliesslich Zahlen und Booleans.
//
// MUTATIONALLY LOCKED: Diese Funktion konstruiert keinen CNSaveRequest und
// ruft store.execute nicht auf.
func opIsolationSummary(_ id: Any) {
    stage("isolation.received")
    guard requireAuth(id) else { stage("isolation.auth_failed"); return }
    stage("isolation.auth_ok")

    // Container: nur Anzahl und Typ, keine Identifier, keine Namen.
    var containerTypes: [String] = []
    do {
        for c in try store.containers(matching: nil) {
            switch c.type {
            case .local: containerTypes.append("local")
            case .exchange: containerTypes.append("exchange")
            case .cardDAV: containerTypes.append("cardDAV")
            case .unassigned: containerTypes.append("unassigned")
            @unknown default: containerTypes.append("unknown")
            }
        }
    } catch let e as NSError {
        stage("isolation.containers_error", error: .providerError)
        fail(id, .providerError, "containers: \(e.domain)/\(e.code)"); return
    }
    stage("isolation.containers_resolved")

    // Me-Card: nil = keine gesetzt (CNContactStore.h:124). Fehler = unknown.
    // Der Identifier bleibt ausschliesslich im Prozessspeicher.
    var meCardPresent: Any = "unknown"
    var meIdentifier: String?
    do {
        let me = try store.unifiedMeContactWithKeys(
            toFetch: [CNContactIdentifierKey as CNKeyDescriptor])
        meIdentifier = me.identifier
        meCardPresent = true
    } catch let e as NSError {
        if e.domain == CNErrorDomain && e.code == CNError.recordDoesNotExist.rawValue {
            meCardPresent = false            // keine Me-Card gesetzt
        } else {
            meCardPresent = "unknown"        // kontrollierter Fehler, keine Vermutung
            diag("meCard-Abfrage fehlgeschlagen: \(e.domain)/\(e.code)")
        }
    }
    stage("isolation.mecard_checked")

    // Enumeration: nur Namensfelder zur Praefixklassifikation. Werte werden
    // ausschliesslich lokal geprueft und nie ausgegeben oder gespeichert.
    let keys: [CNKeyDescriptor] = [
        CNContactIdentifierKey, CNContactGivenNameKey, CNContactFamilyNameKey,
        CNContactOrganizationNameKey,
    ].map { $0 as CNKeyDescriptor }
    let req = CNContactFetchRequest(keysToFetch: keys)
    req.unifyResults = false
    stage("isolation.request_constructed")

    var total = 0, prefixed = 0, foreign = 0
    var seen = Set<String>()
    var duplicates = false
    var meInEnumerate = false
    do {
        stage("isolation.fetch_begin")
        try store.enumerateContacts(with: req) { c, _ in
            total += 1
            if !seen.insert(c.identifier).inserted { duplicates = true }
            if let m = meIdentifier, m == c.identifier { meInEnumerate = true }
            if isTestRecord(c) { prefixed += 1 } else { foreign += 1 }
        }
        stage("isolation.fetch_returned")
    } catch let e as NSError {
        stage("isolation.fetch_error", error: .providerError)
        fail(id, .providerError, "isolation: \(e.domain)/\(e.code)"); return
    }

    ok(id, [
        "authorizationStatus": authStatusText(),
        "containerCount": containerTypes.count,
        "containerTypes": containerTypes.sorted(),
        "totalContacts": total,
        "prefixedTestContacts": prefixed,
        "foreignContacts": foreign,
        "meCardPresent": meCardPresent,
        "meCardIncludedInEnumerate": (meIdentifier == nil)
            ? ("unknown" as Any) : (meInEnumerate as Any),
        "duplicateIdentifiersDetected": duplicates,
        "mutationCount": 0,
        "testPrefix": kTestPrefix,
    ])
    stage("isolation.completed")
}

// ── SPIKE-ONLY: gestufter, AUSSCHLIESSLICH LESENDER Probe-Modus ─────────────
// Isoliert die Absturzgrenze im enumerate-Pfad. Mutiert unter keinen Umstaenden.
// Jede Stufe liefert genau eine eindeutige Antwort oder der Child stirbt — dann
// zeigen die stderr-Stufen, welcher Schluessel zuletzt betreten wurde.
func opEnumerateProbe(_ id: Any, _ params: [String: Any]) {
    stage("enumerate.received")
    guard requireAuth(id) else { stage("enumerate.auth_failed"); return }

    let stageNum = (params["stage"] as? Int) ?? 1
    let group = params["group"] as? String
    var keys: [String] = kProbeStage1
    var label = "stage1-minimal"

    switch stageNum {
    case 1:
        break
    case 2, 3:
        let table = stageNum == 2 ? kProbeStage2 : kProbeStage3
        guard let g = group else {
            fail(id, .invalidRequest, "stage \(stageNum) erfordert 'group'"); return
        }
        guard let entry = table.first(where: { $0.0 == g }) else {
            fail(id, .invalidRequest, "unbekannte group fuer stage \(stageNum)"); return
        }
        keys = kProbeStage1 + entry.1     // Minimum + genau eine Gruppe
        label = "stage\(stageNum)-\(g)"
    default:
        fail(id, .invalidRequest, "stage muss 1, 2 oder 3 sein"); return
    }
    stage("enumerate.validated")
    stage("enumerate.auth_ok")
    stage("enumerate.container_resolved")

    stage("enumerate.keys_begin")
    for k in keys { stage("enumerate.key.\(symbolicKeyName(k))") }
    stage("enumerate.keys_complete")

    let req = CNContactFetchRequest(keysToFetch: keys.map { $0 as CNKeyDescriptor })
    req.unifyResults = false
    stage("enumerate.request_constructed")

    var count = 0
    var serializedFirst = false
    do {
        stage("enumerate.fetch_begin")
        try store.enumerateContacts(with: req) { c, _ in
            if count == 0 { stage("enumerate.callback_entered") }
            // Nur Feld-PRAESENZ pruefen — niemals Werte ausgeben.
            var present: [String] = []
            for k in keys where c.isKeyAvailable(k) {
                present.append(symbolicKeyName(k))
            }
            if !serializedFirst {
                stage("enumerate.serialized")
                serializedFirst = true
                emit(["id": id, "stream": "item",
                      "item": ["keysPresent": present.sorted()]])
                stage("enumerate.response_written")
            }
            count += 1
        }
        stage("enumerate.fetch_returned")
        ok(id, ["count": count, "complete": true, "probe": label,
                "keys": keys.map { symbolicKeyName($0) }.sorted()])
        stage("enumerate.completed")
    } catch let e as NSError {
        stage("enumerate.fetch_error", error: .providerError)
        fail(id, .providerError, "enumerateProbe: \(e.domain)/\(e.code)")
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
    stage("create.received")
    guard requireAuth(id) else { stage("create.failed", error: .tccDenied); return }
    stage("create.auth_ok")
    guard let given = params["givenName"] as? String,
          let family = params["familyName"] as? String else {
        stage("create.failed", error: .invalidRequest)
        fail(id, .invalidRequest, "givenName/familyName fehlen"); return
    }
    guard given.hasPrefix(kTestPrefix) || family.hasPrefix(kTestPrefix) else {
        stage("create.failed", error: .forbidden)
        fail(id, .forbidden, "Spike-Rail: nur \(kTestPrefix)-Datensätze"); return
    }
    stage("create.validated")
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
    // `note` erfordert seit macOS 11 das Entitlement
    // com.apple.developer.contacts.notes. Der Spike-Sidecar traegt bewusst KEINE
    // Entitlements — das Feld wird daher nur auf ausdrueckliche Anforderung
    // gesetzt und ist im gestuften Ablauf ein eigener, isolierter Testschritt.
    if let noteText = params["note"] as? String {
        stage("create.note_set_attempted")
        c.note = noteText
    }
    stage("create.contact_constructed")

    let req = CNSaveRequest()
    req.transactionAuthor = kTransactionAuthor
    req.add(c, toContainerWithIdentifier: params["containerIdentifier"] as? String)
    stage("create.container_resolved")
    do {
        stage("create.save_begin")
        try store.execute(req)
        stage("create.save_returned")
        let verified = (try? fetchRaw(identifier: c.identifier)) != nil
        ok(id, ["identifier": c.identifier, "verified": verified])
        stage("create.response_written")
    } catch let e as NSError {
        stage("create.failed", error: .providerError)
        fail(id, .providerError, "create: \(e.domain)/\(e.code) \(e.localizedDescription)")
        stage("create.response_written")
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
    "caps": ["ping", "caps", "containers", "enumerate", "enumerateProbe",
             "isolationSummary",
             "changes", "token", "get", "getUnified", "create", "update",
             "updateViaUnified", "delete", "requestAuthorization", "shutdown"],
    "limits": ["mutationsRestrictedToPrefix": kTestPrefix,
               "linkUnlinkSupported": false,   // CNSaveRequest hat keine Link-API
               // Notes-Zugriff verlangt com.apple.developer.contacts.notes.
               // Der Sidecar traegt bewusst KEINE Entitlements — die Faehigkeit
               // wird daher ausdruecklich als nicht verfuegbar gemeldet und der
               // Note-Key ist nicht Teil des Standard-Fetch. Kein Leerwert.
               "notesSupported": false,
               "notesUnavailableReason": "missing-entitlement"],
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
    case "enumerateProbe":   opEnumerateProbe(id, params)
    case "isolationSummary": opIsolationSummary(id)
    case "caps":             ok(id, ["notesSupported": false,
                                     "probeStagesSupported": true,
                                     "protocol": kProtocolVersion,
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

//  main.swift — SPIKE G3a (ADR-0016) P0-Reachability-Probe. Temporär, nicht produktiv.
//
//  Zweck: nachweisen, dass die von Apple als NS_SWIFT_UNAVAILABLE("") markierte
//  Change-History-API über eine REINE Weiterleitung (JCChangeHistoryShim)
//  aus Swift erreichbar und typkorrekt gebrückt ist.
//
//  SICHERHEIT (E5): Ohne das Argument --run-fetch findet KEIN Kontaktzugriff
//  statt. Der Standardlauf liest ausschließlich den Autorisierungsstatus
//  (löst keinen TCC-Dialog aus und liefert keine Kontaktdaten).

import Foundation
import Contacts

// ── Beweis 1: CNChangeHistoryEventVisitor ist aus Swift konformierbar ──────────
final class ProbeVisitor: NSObject, CNChangeHistoryEventVisitor {
    var adds = 0, updates = 0, deletes = 0, drops = 0

    func visit(_ event: CNChangeHistoryDropEverythingEvent) { drops += 1 }
    func visit(_ event: CNChangeHistoryAddContactEvent) { adds += 1 }
    func visit(_ event: CNChangeHistoryUpdateContactEvent) { updates += 1 }
    func visit(_ event: CNChangeHistoryDeleteContactEvent) { deletes += 1 }
}

func err(_ s: String) { FileHandle.standardError.write((s + "\n").data(using: .utf8)!) }
func out(_ s: String) { print(s) }

// ── Beweis 2: Typen sind konstruierbar, Symbole werden gelinkt ─────────────────
let store = CNContactStore()

let historyRequest = CNChangeHistoryFetchRequest()
historyRequest.shouldUnifyResults = false          // Roh-Datensätze (Schlüsselstrategie)
historyRequest.includeGroupChanges = false
historyRequest.excludedTransactionAuthors = ["de.jarvis.contacts-spike"]

let keys: [CNKeyDescriptor] = [
    CNContactIdentifierKey as CNKeyDescriptor,
    CNContactGivenNameKey as CNKeyDescriptor,
    CNContactFamilyNameKey as CNKeyDescriptor,
]
let contactRequest = CNContactFetchRequest(keysToFetch: keys)
contactRequest.unifyResults = false

let status = CNContactStore.authorizationStatus(for: .contacts)
let statusText: String
switch status {
case .notDetermined: statusText = "notDetermined"
case .restricted:    statusText = "restricted"
case .denied:        statusText = "denied"
case .authorized:    statusText = "authorized"
@unknown default:    statusText = "unknown(\(status.rawValue))"
}

out("P0: shim-symbols-linked=yes")
out("P0: visitor-conformable=yes")
out("P0: history-request-constructed=yes")
out("P0: contact-request-constructed=yes")
out("P0: authorization-status=\(statusText)")

// ── Beweis 3: Aufruf über den Shim — nur mit ausdrücklichem Flag ───────────────
// Ab hier wird der Kontakte-Store tatsächlich berührt (auch currentHistoryToken).
// Ohne --run-fetch endet das Programm vorher: kein Store-Zugriff, kein TCC-Dialog.
guard CommandLine.arguments.contains("--run-fetch") else {
    out("P0: fetch-skipped=yes (kein --run-fetch; kein Store-Zugriff)")
    exit(0)
}

out("P0: current-history-token-readable=\(store.currentHistoryToken != nil)")

guard status == .authorized else {
    err("P0: fetch abgebrochen — Autorisierung ist \(statusText), nicht authorized.")
    exit(2)
}

do {
    // Delta-Pfad über die Weiterleitung (NS_SWIFT_UNAVAILABLE ohne Shim)
    let historyResult = try JCChangeHistoryShim.changeHistoryEnumerator(
        for: store, request: historyRequest)
    let visitor = ProbeVisitor()
    var eventCount = 0
    while let event = historyResult.value.nextObject() as? CNChangeHistoryEvent {
        event.accept(visitor)
        eventCount += 1
    }
    out("P0: history-events=\(eventCount) adds=\(visitor.adds) updates=\(visitor.updates) deletes=\(visitor.deletes) drops=\(visitor.drops)")
    out("P0: history-token-bytes=\(historyResult.currentHistoryToken.count)")

    // Fallback-Pfad über die Weiterleitung (ebenfalls NS_SWIFT_UNAVAILABLE)
    let contactResult = try JCChangeHistoryShim.contactEnumerator(
        for: store, request: contactRequest)
    var contactCount = 0
    while contactResult.value.nextObject() != nil { contactCount += 1 }
    out("P0: enumerated-contacts=\(contactCount)")
    out("P0: fetch=ok")
} catch let e as NSError {
    err("P0: fetch-error domain=\(e.domain) code=\(e.code) desc=\(e.localizedDescription)")
    exit(3)
}

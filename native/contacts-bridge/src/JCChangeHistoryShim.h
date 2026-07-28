//  JCChangeHistoryShim.h — produktive Kontakte-Bridge.
//
//  Zweck: reine Selektor-Weiterleitung der von Apple als
//  NS_SWIFT_UNAVAILABLE("") markierten CNContactStore-Methoden
//  (CNContactStore.h: enumeratorForChangeHistoryFetchRequest:error:,
//  enumeratorForContactFetchRequest:error:).
//
//  VERBOTEN in dieser Datei (ADR-0016 Punkt 4):
//  keine Fachlogik, keine Workspaces, keine Merge-Entscheidungen, keine
//  Risikobewertung, keine Auditlogik, keine Speicherung, keine
//  Normalisierung, kein Hashing. Ausschliesslich Aufrufweiterleitung.

#import <Foundation/Foundation.h>
#import <Contacts/Contacts.h>

NS_ASSUME_NONNULL_BEGIN

@interface JCChangeHistoryShim : NSObject

/// Weiterleitung von -[CNContactStore enumeratorForChangeHistoryFetchRequest:error:]
+ (nullable CNFetchResult<NSEnumerator<CNChangeHistoryEvent *> *> *)
    changeHistoryEnumeratorForStore:(CNContactStore *)store
                            request:(CNChangeHistoryFetchRequest *)request
                              error:(NSError *_Nullable *_Nullable)error
    NS_SWIFT_NAME(changeHistoryEnumerator(for:request:));

/// Weiterleitung von -[CNContactStore enumeratorForContactFetchRequest:error:]
+ (nullable CNFetchResult<NSEnumerator<CNContact *> *> *)
    contactEnumeratorForStore:(CNContactStore *)store
                      request:(CNContactFetchRequest *)request
                        error:(NSError *_Nullable *_Nullable)error
    NS_SWIFT_NAME(contactEnumerator(for:request:));

@end

NS_ASSUME_NONNULL_END

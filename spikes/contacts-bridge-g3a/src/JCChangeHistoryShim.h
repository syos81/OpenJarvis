//  JCChangeHistoryShim.h — SPIKE G3a (ADR-0016), temporär, nicht produktiv.
//
//  Zweck: reine Weiterleitung der von Apple als NS_SWIFT_UNAVAILABLE("")
//  markierten CNContactStore-Methoden (CNContactStore.h:147,165).
//
//  VERBOTEN in dieser Datei (ADR-0016 §4 / E3):
//  keine Fachlogik, keine Workspaces, keine Merge-Entscheidungen,
//  keine Risikobewertung, keine Auditlogik, keine Speicherung,
//  keine Normalisierung, kein Hashing. Ausschließlich Aufrufweiterleitung.

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

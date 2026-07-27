//  JCChangeHistoryShim.m — SPIKE G3a (ADR-0016), temporär, nicht produktiv.
//  Reine Aufrufweiterleitung. Keine weitere Logik (E3).

#import "JCChangeHistoryShim.h"

@implementation JCChangeHistoryShim

+ (CNFetchResult<NSEnumerator<CNChangeHistoryEvent *> *> *)
    changeHistoryEnumeratorForStore:(CNContactStore *)store
                            request:(CNChangeHistoryFetchRequest *)request
                              error:(NSError *_Nullable *_Nullable)error {
    return [store enumeratorForChangeHistoryFetchRequest:request error:error];
}

+ (CNFetchResult<NSEnumerator<CNContact *> *> *)
    contactEnumeratorForStore:(CNContactStore *)store
                      request:(CNContactFetchRequest *)request
                        error:(NSError *_Nullable *_Nullable)error {
    return [store enumeratorForContactFetchRequest:request error:error];
}

@end

//  JCBridgingHeader.h — Sammelheader fuer swiftc -import-objc-header.
//
//  swiftc nimmt genau EINEN Bridging-Header; hier werden die beiden
//  produktiven Objective-C-Shims zusammengefuehrt. Fachlogik hat in dieser
//  Datei nichts verloren — sie importiert ausschliesslich.

#import "JCChangeHistoryShim.h"
#import "JCContactsSaveShim.h"

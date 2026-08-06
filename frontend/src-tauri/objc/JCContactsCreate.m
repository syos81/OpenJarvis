//  JCContactsCreate.m — produktiver Create im App-Prozess.
//
//  Aufbau, bewusst wie im belegten Spike, aber ohne dessen Sonderlogik:
//
//  1. Ein Operationsobjekt (Blocks) trennt den Ablauf von der Store-Anbindung.
//     Der Produktivpfad füllt es mit echten CNContactStore-Aufrufen, der
//     kontaktfreie Testeinstieg mit Fakes. Der Ablauf selbst ist EINE
//     Funktion — es gibt keinen zweiten Weg zum Save.
//  2. Der Save läuft in einer Objective-C-@try/@catch-Grenze; zusätzlich ist
//     die Uncaught-Letztdiagnose installiert (der Dispatch-Wurf des Sidecars
//     erreichte kein @catch — Crashreport-Beleg 2026-08-02).
//  3. Der Roh-Reason existiert nur im Diagnoseartefakt (Ordner 0700, Datei
//     exklusiv 0600); öffentlich reisen Klassenname und SHA-256-Digest.
//
//  Feldabbildung: ausschliesslich der eingefrorene v1-Vertrag (ADR-0026 §7).
//  Ein unbekannter Schlüssel ist kein „ignorieren", sondern
//  `InvalidPayload` — vor jedem Store-Zugriff.

#import "JCContactsCreate.h"

#import <Contacts/Contacts.h>
#import <CommonCrypto/CommonDigest.h>
#import <sys/stat.h>
#import <sys/utsname.h>
#import <fcntl.h>
#import <unistd.h>
#import <string.h>

static NSString *const kDiagnosticsEnvVar =
    @"OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH";

// ── C-nahe Hilfen (terminierungsfest) ───────────────────────────────────────

static void JCCreateSha256Hex(const char *bytes, size_t len, char out[65]) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(bytes, (CC_LONG)len, digest);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        out[i * 2]     = hex[digest[i] >> 4];
        out[i * 2 + 1] = hex[digest[i] & 0x0F];
    }
    out[64] = '\0';
}

static void JCCreateSanitizeName(const char *_Nullable name, char out[65]) {
    size_t n = 0;
    for (const char *p = name; p != NULL && *p != '\0' && n < 64; p++) {
        char c = *p;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
            || (c >= '0' && c <= '9') || c == '_') {
            out[n++] = c;
        }
    }
    if (n == 0) { strlcpy(out, "UnknownException", 65); } else { out[n] = '\0'; }
}

static void JCCreateSanitizeDomain(const char *_Nullable domain, char out[128]) {
    size_t n = 0;
    for (const char *p = domain; p != NULL && *p != '\0' && n < 127; p++) {
        char c = *p;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
            || (c >= '0' && c <= '9') || c == '.' || c == '_') {
            out[n++] = c;
        }
    }
    out[n] = '\0';
    if (n == 0) { strlcpy(out, "UnknownDomain", 128); }
}

// ── Diagnoseartefakt: 0700-Ordner, 0600-Datei, exklusiv angelegt ────────────

static struct {
    int  fd;
    long sequence;
    char arch[32];
    char os[32];
    double preparedAt;
} gCreateDiag = { .fd = -1 };

static char gCreateDiagPath[1024];

static BOOL JCCreateDiagDirUsable(NSString *dir) {
    if (dir.length == 0 || ![dir hasPrefix:@"/"]) { return NO; }
    struct stat st;
    if (lstat(dir.fileSystemRepresentation, &st) != 0) { return NO; }
    if (S_ISLNK(st.st_mode) || !S_ISDIR(st.st_mode)) { return NO; }
    if (st.st_uid != geteuid()) { return NO; }
    if ((st.st_mode & 0777) != 0700) { return NO; }
    return YES;
}

static void JCCreateDiscardDiag(void) {
    if (gCreateDiag.fd < 0) { return; }
    close(gCreateDiag.fd);
    unlink(gCreateDiagPath);
    gCreateDiag.fd = -1;
}

static void JCCreatePrepareDiag(void) {
    if (gCreateDiag.fd >= 0) { JCCreateDiscardDiag(); }
    NSString *dir = NSProcessInfo.processInfo.environment[kDiagnosticsEnvVar];
    if (dir == nil || !JCCreateDiagDirUsable(dir)) { return; }

    struct utsname uts;
    strlcpy(gCreateDiag.arch, uname(&uts) == 0 ? uts.machine : "unknown",
            sizeof(gCreateDiag.arch));
    NSOperatingSystemVersion os =
        NSProcessInfo.processInfo.operatingSystemVersion;
    snprintf(gCreateDiag.os, sizeof(gCreateDiag.os), "%ld.%ld.%ld",
             (long)os.majorVersion, (long)os.minorVersion,
             (long)os.patchVersion);
    gCreateDiag.preparedAt = [NSDate date].timeIntervalSince1970;
    static long seq = 0;
    gCreateDiag.sequence = ++seq;

    NSString *name = [NSString stringWithFormat:
        @"contacts-create-exception-%.0f-%d-%ld.json",
        gCreateDiag.preparedAt * 1000.0, getpid(), gCreateDiag.sequence];
    NSString *path = [dir stringByAppendingPathComponent:name];
    if (strlcpy(gCreateDiagPath, path.fileSystemRepresentation,
                sizeof(gCreateDiagPath)) >= sizeof(gCreateDiagPath)) {
        return;
    }
    int fd = open(gCreateDiagPath,
                  O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd >= 0) { gCreateDiag.fd = fd; }
}

static void JCCreateWriteLiteral(int fd, const char *s) {
    write(fd, s, strlen(s));
}

static void JCCreateWriteJsonEscaped(int fd, const char *_Nullable s,
                                     size_t maxBytes) {
    if (s == NULL) { return; }
    char puffer[512];
    size_t p = 0;
    for (size_t i = 0; s[i] != '\0' && i < maxBytes; i++) {
        unsigned char c = (unsigned char)s[i];
        if (p > sizeof(puffer) - 8) { write(fd, puffer, p); p = 0; }
        if (c == '"' || c == '\\') {
            puffer[p++] = '\\'; puffer[p++] = (char)c;
        } else if (c < 0x20) {
            p += (size_t)snprintf(puffer + p, 8, "\\u%04x", c);
        } else {
            puffer[p++] = (char)c;
        }
    }
    if (p > 0) { write(fd, puffer, p); }
}

#define JC_CREATE_REASON_MAX 4096

static BOOL JCCreateCommitDiag(const char *source, const char name[65],
                               const char *_Nullable reasonUtf8,
                               const char *_Nullable digestHex) {
    if (gCreateDiag.fd < 0) { return NO; }
    int fd = gCreateDiag.fd;
    char zahl[64];
    JCCreateWriteLiteral(fd, "{\"source\":\"");
    JCCreateWriteLiteral(fd, source);
    JCCreateWriteLiteral(fd, "\",\"preparedAt\":");
    snprintf(zahl, sizeof(zahl), "%.3f", gCreateDiag.preparedAt);
    JCCreateWriteLiteral(fd, zahl);
    JCCreateWriteLiteral(fd, ",\"exceptionName\":\"");
    JCCreateWriteJsonEscaped(fd, name, 64);
    JCCreateWriteLiteral(fd, "\",\"reasonPresent\":");
    JCCreateWriteLiteral(fd, reasonUtf8 ? "true" : "false");
    if (reasonUtf8 != NULL) {
        JCCreateWriteLiteral(fd, ",\"reasonTruncated\":");
        JCCreateWriteLiteral(fd,
            strlen(reasonUtf8) > JC_CREATE_REASON_MAX ? "true" : "false");
        JCCreateWriteLiteral(fd, ",\"reason\":\"");
        JCCreateWriteJsonEscaped(fd, reasonUtf8, JC_CREATE_REASON_MAX);
        JCCreateWriteLiteral(fd, "\"");
    }
    if (digestHex != NULL) {
        JCCreateWriteLiteral(fd, ",\"reasonDigest\":\"");
        JCCreateWriteLiteral(fd, digestHex);
        JCCreateWriteLiteral(fd, "\"");
    }
    JCCreateWriteLiteral(fd, ",\"architecture\":\"");
    JCCreateWriteJsonEscaped(fd, gCreateDiag.arch, sizeof(gCreateDiag.arch));
    JCCreateWriteLiteral(fd, "\",\"osVersion\":\"");
    JCCreateWriteJsonEscaped(fd, gCreateDiag.os, sizeof(gCreateDiag.os));
    JCCreateWriteLiteral(fd, "\"}");
    BOOL ok = (fsync(fd) == 0);
    close(fd);
    gCreateDiag.fd = -1;
    return ok;
}

// ── Uncaught-Letztdiagnose (Kette zum fremden Handler bleibt erhalten) ──────

static NSUncaughtExceptionHandler *gCreatePreviousHandler = NULL;
static BOOL gCreateUncaughtInstalled = NO;

static void JCCreateUncaughtHandler(NSException *exception) {
    char name[65];
    JCCreateSanitizeName(exception.name.UTF8String, name);
    const char *reason = exception.reason.UTF8String;
    char digest[65];
    const char *digestPtr = NULL;
    if (reason != NULL) {
        JCCreateSha256Hex(reason, strlen(reason), digest);
        digestPtr = digest;
    }
    JCCreateWriteLiteral(STDERR_FILENO,
        "[contacts-create] uncaught_objc_exception name=");
    JCCreateWriteLiteral(STDERR_FILENO, name);
    JCCreateWriteLiteral(STDERR_FILENO, " reasonDigest=");
    JCCreateWriteLiteral(STDERR_FILENO, digestPtr ? digestPtr : "unavailable");
    JCCreateWriteLiteral(STDERR_FILENO, "\n");
    if (gCreateDiag.fd >= 0) {
        JCCreateCommitDiag("create-uncaught", name, reason, digestPtr);
    }
    if (gCreatePreviousHandler != NULL) { gCreatePreviousHandler(exception); }
}

static void JCCreateInstallUncaught(void) {
    if (gCreateUncaughtInstalled) { return; }
    gCreateUncaughtInstalled = YES;
    gCreatePreviousHandler = NSGetUncaughtExceptionHandler();
    NSSetUncaughtExceptionHandler(&JCCreateUncaughtHandler);
}

// ── Feldvertrag v1: Abbildung in beide Richtungen ───────────────────────────
//
// Die Tabellen sind die einzige Stelle, an der ein Feldname auf ein
// CN-Ziel trifft. Was hier nicht steht, ist nicht schreibbar — und wird
// nicht stillschweigend übergangen, sondern abgewiesen.

static NSDictionary<NSString *, NSString *> *JCCreateScalarKeys(void) {
    static NSDictionary *tabelle = nil;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        tabelle = @{
            @"givenName": @"givenName",
            @"middleName": @"middleName",
            @"familyName": @"familyName",
            @"previousFamilyName": @"previousFamilyName",
            @"namePrefix": @"namePrefix",
            @"nameSuffix": @"nameSuffix",
            @"nickname": @"nickname",
            @"phoneticGivenName": @"phoneticGivenName",
            @"phoneticFamilyName": @"phoneticFamilyName",
            @"organizationName": @"organizationName",
            @"departmentName": @"departmentName",
            @"jobTitle": @"jobTitle",
        };
    });
    return tabelle;
}

/// Kanonisches Label → CN-Label. `null`/fehlend heisst „ohne Etikett".
static NSString *_Nullable JCCreateCNLabel(id roh) {
    if (roh == nil || roh == NSNull.null) { return nil; }
    NSString *l = (NSString *)roh;
    if ([l isEqualToString:@"home"]) { return CNLabelHome; }
    if ([l isEqualToString:@"work"]) { return CNLabelWork; }
    if ([l isEqualToString:@"other"]) { return CNLabelOther; }
    if ([l isEqualToString:@"mobile"]) { return CNLabelPhoneNumberMobile; }
    if ([l isEqualToString:@"main"]) { return CNLabelPhoneNumberMain; }
    return nil;
}

/// CN-Label → kanonisches Label. Unbekanntes wird zu `nil` (ohne Etikett) —
/// der Vergleich im Kern schlägt dann fehl, statt etwas zu erfinden.
static NSString *_Nullable JCCreateCanonicalLabel(NSString *_Nullable cn) {
    if (cn == nil) { return nil; }
    if ([cn isEqualToString:CNLabelHome]) { return @"home"; }
    if ([cn isEqualToString:CNLabelWork]) { return @"work"; }
    if ([cn isEqualToString:CNLabelOther]) { return @"other"; }
    if ([cn isEqualToString:CNLabelPhoneNumberMobile]) { return @"mobile"; }
    if ([cn isEqualToString:CNLabelPhoneNumberMain]) { return @"main"; }
    return nil;
}

static NSArray<NSString *> *JCCreateAllowedKeys(void) {
    static NSArray *keys = nil;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        NSMutableArray *alle = [NSMutableArray arrayWithArray:
            JCCreateScalarKeys().allKeys];
        [alle addObjectsFromArray:@[ @"contactType", @"birthday", @"emails",
                                     @"phones", @"postalAddresses", @"urls",
                                     @"dates" ]];
        keys = [alle copy];
    });
    return keys;
}

static NSDateComponents *_Nullable JCCreateComponents(NSDictionary *roh) {
    id monat = roh[@"month"], tag = roh[@"day"];
    if (![monat isKindOfClass:NSNumber.class]
        || ![tag isKindOfClass:NSNumber.class]) { return nil; }
    NSDateComponents *k = [[NSDateComponents alloc] init];
    k.month = [monat integerValue];
    k.day = [tag integerValue];
    id jahr = roh[@"year"];
    if ([jahr isKindOfClass:NSNumber.class]) { k.year = [jahr integerValue]; }
    k.calendar = [NSCalendar calendarWithIdentifier:NSCalendarIdentifierGregorian];
    return k;
}

static NSDictionary *_Nullable JCCreateDateDict(NSDateComponents *_Nullable k) {
    if (k == nil) { return nil; }
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    if (k.year != NSDateComponentUndefined && k.year != 0) {
        out[@"year"] = @(k.year);
    }
    if (k.month == NSDateComponentUndefined || k.day == NSDateComponentUndefined) {
        return nil;
    }
    out[@"month"] = @(k.month);
    out[@"day"] = @(k.day);
    return out;
}

/// Baut den einen Kontakt. Gibt `nil` zurück, wenn die Nutzlast den v1-
/// Vertrag verletzt — dann gibt es keinen Save.
/// Setzt die fünf etikettierten Listen auf `ziel`.
///
/// `patch` unterscheidet die beiden Bedeutungen von `null`: beim Create ist
/// eine fehlende Liste schlicht nicht gesetzt, beim Update ist ein
/// ausdrückliches `null` beziehungsweise `[]` die Anweisung, alle Werte zu
/// löschen. Ohne diese Unterscheidung könnte ein Update nichts leeren —
/// oder, schlimmer, ein Weglassen würde löschen.
static BOOL JCCreateApplyLists(CNMutableContact *ziel, NSDictionary *quelle,
                               BOOL patch) {
    // Etikettierte Listen — Reihenfolge ist Position, keine Sortierung.
    NSArray *mails = quelle[@"emails"];
    if (mails == NSNull.null && patch) { ziel.emailAddresses = @[]; }
    else if (mails != nil && mails != NSNull.null) {
        if (![mails isKindOfClass:NSArray.class]) { return NO; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *e in mails) {
            if (![e isKindOfClass:NSDictionary.class]) { return NO; }
            NSString *v = e[@"value"];
            if (![v isKindOfClass:NSString.class]) { return NO; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(e[@"label"]) value:v]];
        }
        ziel.emailAddresses = werte;
    }

    NSArray *rufnummern = quelle[@"phones"];
    if (rufnummern == NSNull.null && patch) { ziel.phoneNumbers = @[]; }
    else if (rufnummern != nil && rufnummern != NSNull.null) {
        if (![rufnummern isKindOfClass:NSArray.class]) { return NO; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *p in rufnummern) {
            if (![p isKindOfClass:NSDictionary.class]) { return NO; }
            NSString *v = p[@"value"];
            if (![v isKindOfClass:NSString.class]) { return NO; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(p[@"label"])
                        value:[CNPhoneNumber phoneNumberWithStringValue:v]]];
        }
        ziel.phoneNumbers = werte;
    }

    NSArray *adressen = quelle[@"postalAddresses"];
    if (adressen == NSNull.null && patch) { ziel.postalAddresses = @[]; }
    else if (adressen != nil && adressen != NSNull.null) {
        if (![adressen isKindOfClass:NSArray.class]) { return NO; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *a in adressen) {
            if (![a isKindOfClass:NSDictionary.class]) { return NO; }
            CNMutablePostalAddress *pa = [[CNMutablePostalAddress alloc] init];
            NSDictionary *teile = @{ @"street": @"street", @"city": @"city",
                                     @"state": @"state",
                                     @"postalCode": @"postalCode",
                                     @"country": @"country",
                                     @"isoCountryCode": @"ISOCountryCode" };
            for (NSString *k in teile) {
                id v = a[k];
                if (v == nil || v == NSNull.null) { continue; }
                if (![v isKindOfClass:NSString.class]) { return NO; }
                [pa setValue:v forKey:teile[k]];
            }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(a[@"label"]) value:pa]];
        }
        ziel.postalAddresses = werte;
    }

    NSArray *adressenWeb = quelle[@"urls"];
    if (adressenWeb == NSNull.null && patch) { ziel.urlAddresses = @[]; }
    else if (adressenWeb != nil && adressenWeb != NSNull.null) {
        if (![adressenWeb isKindOfClass:NSArray.class]) { return NO; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *u in adressenWeb) {
            if (![u isKindOfClass:NSDictionary.class]) { return NO; }
            NSString *v = u[@"value"];
            if (![v isKindOfClass:NSString.class]) { return NO; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(u[@"label"]) value:v]];
        }
        ziel.urlAddresses = werte;
    }

    NSArray *daten = quelle[@"dates"];
    if (daten == NSNull.null && patch) { ziel.dates = @[]; }
    else if (daten != nil && daten != NSNull.null) {
        if (![daten isKindOfClass:NSArray.class]) { return NO; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *d in daten) {
            if (![d isKindOfClass:NSDictionary.class]) { return NO; }
            NSDateComponents *k = JCCreateComponents(d);
            if (k == nil) { return NO; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(d[@"label"]) value:k]];
        }
        ziel.dates = werte;
    }

    return YES;
}


/// Schreibt den `save_started`-Marker — unmittelbar vor der Übergabe.
///
/// Der Marker ist die Antwort auf den SIGABRT vom 2026-08-04: Die CoreData-
/// Ausnahme überquert eine Dispatch-Grenze und ist prinzipiell nicht
/// fangbar. Stirbt der Prozess, unterscheidet allein diese Datei die beiden
/// Wahrheiten „nachweislich nichts übergeben" (kein Marker → not_sent) und
/// „möglicherweise gesendet" (Marker → outcome_unknown). PII-frei: Phase
/// und Operation, sonst nichts.
static void JCCreateWriteSaveMarker(const char *operation) {
    const char *pfad = getenv("OPENJARVIS_CONTACTS_SAVE_MARKER");
    if (pfad == NULL || pfad[0] != '/') { return; }
    int fd = open(pfad, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) { return; }
    char zeile[128];
    int n = snprintf(zeile, sizeof(zeile),
                     "{\"phase\":\"save_started\",\"operation\":\"%s\"}",
                     operation);
    if (n > 0) { write(fd, zeile, (size_t)n); }
    fsync(fd);
    close(fd);
}

static CNMutableContact *_Nullable JCCreateBuildContact(NSDictionary *payload) {
    NSSet *erlaubt = [NSSet setWithArray:JCCreateAllowedKeys()];
    for (NSString *schluessel in payload) {
        if (![erlaubt containsObject:schluessel]) { return nil; }
    }

    CNMutableContact *neu = [[CNMutableContact alloc] init];

    id typ = payload[@"contactType"];
    if ([typ isEqual:@"organization"]) {
        neu.contactType = CNContactTypeOrganization;
    } else if (typ == nil || [typ isEqual:@"person"]) {
        neu.contactType = CNContactTypePerson;
    } else {
        return nil;
    }

    NSDictionary *skalare = JCCreateScalarKeys();
    for (NSString *schluessel in skalare) {
        id wert = payload[schluessel];
        if (wert == nil || wert == NSNull.null) { continue; }
        if (![wert isKindOfClass:NSString.class]) { return nil; }
        [neu setValue:wert forKey:skalare[schluessel]];
    }

    id geburtstag = payload[@"birthday"];
    if (geburtstag != nil && geburtstag != NSNull.null) {
        if (![geburtstag isKindOfClass:NSDictionary.class]) { return nil; }
        NSDateComponents *k = JCCreateComponents(geburtstag);
        if (k == nil) { return nil; }
        neu.birthday = k;
    }

    if (!JCCreateApplyLists(neu, payload, NO)) { return nil; }

    return neu;
}

/// Die Schlüsselmenge des Read-backs — genau die v1-Felder, nichts darüber.
/// Insbesondere **kein** Notiz- und kein Bildschlüssel.
static NSArray<id<CNKeyDescriptor>> *JCCreateReadbackKeys(void) {
    return @[ CNContactIdentifierKey, CNContactTypeKey,
              CNContactGivenNameKey, CNContactMiddleNameKey,
              CNContactFamilyNameKey, CNContactPreviousFamilyNameKey,
              CNContactNamePrefixKey, CNContactNameSuffixKey,
              CNContactNicknameKey, CNContactPhoneticGivenNameKey,
              CNContactPhoneticFamilyNameKey, CNContactOrganizationNameKey,
              CNContactDepartmentNameKey, CNContactJobTitleKey,
              CNContactBirthdayKey, CNContactDatesKey,
              CNContactEmailAddressesKey, CNContactPhoneNumbersKey,
              CNContactPostalAddressesKey, CNContactUrlAddressesKey ];
}

/// Projiziert einen gelesenen Kontakt auf die kanonische v1-Form. Leere
/// Werte erscheinen **nicht** — genau wie im Kern, damit „weggelassen" und
/// „leer" denselben Digest ergeben.
static NSDictionary *JCCreateProject(CNContact *kontakt) {
    NSMutableDictionary *out = [NSMutableDictionary dictionary];
    out[@"contactType"] = (kontakt.contactType == CNContactTypeOrganization)
        ? @"organization" : @"person";

    NSDictionary *skalare = JCCreateScalarKeys();
    for (NSString *schluessel in skalare) {
        NSString *wert = [kontakt valueForKey:skalare[schluessel]];
        if (wert.length > 0) { out[schluessel] = wert; }
    }

    NSDictionary *geburtstag = JCCreateDateDict(kontakt.birthday);
    if (geburtstag != nil) { out[@"birthday"] = geburtstag; }

    NSMutableArray *mails = [NSMutableArray array];
    for (CNLabeledValue<NSString *> *e in kontakt.emailAddresses) {
        NSString *label = JCCreateCanonicalLabel(e.label);
        [mails addObject:@{ @"label": label ?: NSNull.null,
                            @"value": e.value ?: @"" }];
    }
    if (mails.count > 0) { out[@"emails"] = mails; }

    NSMutableArray *rufnummern = [NSMutableArray array];
    for (CNLabeledValue<CNPhoneNumber *> *p in kontakt.phoneNumbers) {
        NSString *label = JCCreateCanonicalLabel(p.label);
        [rufnummern addObject:@{ @"label": label ?: NSNull.null,
                                 @"value": p.value.stringValue ?: @"" }];
    }
    if (rufnummern.count > 0) { out[@"phones"] = rufnummern; }

    NSMutableArray *adressen = [NSMutableArray array];
    for (CNLabeledValue<CNPostalAddress *> *a in kontakt.postalAddresses) {
        NSMutableDictionary *eintrag = [NSMutableDictionary dictionary];
        NSString *label = JCCreateCanonicalLabel(a.label);
        eintrag[@"label"] = label ?: NSNull.null;
        NSDictionary *teile = @{ @"street": a.value.street,
                                 @"city": a.value.city,
                                 @"state": a.value.state,
                                 @"postalCode": a.value.postalCode,
                                 @"country": a.value.country,
                                 @"isoCountryCode": a.value.ISOCountryCode };
        for (NSString *k in teile) {
            NSString *v = teile[k];
            if (v.length > 0) { eintrag[k] = v; }
        }
        [adressen addObject:eintrag];
    }
    if (adressen.count > 0) { out[@"postalAddresses"] = adressen; }

    NSMutableArray *adressenWeb = [NSMutableArray array];
    for (CNLabeledValue<NSString *> *u in kontakt.urlAddresses) {
        NSString *label = JCCreateCanonicalLabel(u.label);
        [adressenWeb addObject:@{ @"label": label ?: NSNull.null,
                                  @"value": u.value ?: @"" }];
    }
    if (adressenWeb.count > 0) { out[@"urls"] = adressenWeb; }

    NSMutableArray *daten = [NSMutableArray array];
    for (CNLabeledValue<NSDateComponents *> *d in kontakt.dates) {
        NSDictionary *wert = JCCreateDateDict(d.value);
        if (wert == nil) { continue; }
        NSMutableDictionary *eintrag = [wert mutableCopy];
        NSString *label = JCCreateCanonicalLabel(d.label);
        eintrag[@"label"] = label ?: NSNull.null;
        [daten addObject:eintrag];
    }
    if (daten.count > 0) { out[@"dates"] = daten; }

    return out;
}

// ── Operationsobjekt: der eine Ablauf, zwei Anbindungen ─────────────────────

typedef NS_ENUM(int32_t, JCCreateAuth) {
    JCCreateAuthNotAuthorized = 0,
    JCCreateAuthAuthorized = 1,
};

@interface JCCreateOps : NSObject
/// CNAuthorizationStatus lesen — nie anfordern.
@property (nonatomic, copy) JCCreateAuth (^authorization)(void);
/// Existiert **genau dieser** Container? Der Shim sucht sich keinen aus.
@property (nonatomic, copy) BOOL (^containerExists)(NSString *identifier,
                                                    NSError *__autoreleasing *);
/// Minimaler Fetch auf eine nicht existente Kennung — beweist, dass der
/// Lesestapel steht, ohne einen fremden Kontakt anzufassen.
@property (nonatomic, copy) BOOL (^probeFetch)(NSError *__autoreleasing *);
/// GENAU EIN Save. Liefert bei Erfolg die neue Providerkennung.
@property (nonatomic, copy) NSString *_Nullable (^save)
    (CNMutableContact *kontakt, NSString *containerIdentifier,
     NSString *transactionAuthor, NSError *__autoreleasing *error);
/// Read-back über **genau diese** Kennung — nie über den Namen.
@property (nonatomic, copy) NSDictionary *_Nullable (^readback)
    (NSString *providerIdentifier);
@end

@implementation JCCreateOps
@end

// ── Der eine Ablauf ─────────────────────────────────────────────────────────

static void JCCreateRun(JCCreateOps *ops, NSDictionary *payload,
                        NSString *containerIdentifier,
                        NSString *transactionAuthor,
                        JCContactsCreateResult *out) {
    memset(out, 0, sizeof(*out));
    JCCreateInstallUncaught();

    // 1. Autorisierung — lesen, nie anfordern.
    if (ops.authorization() != JCCreateAuthAuthorized) {
        out->outcome = JCContactsCreateOutcomeNotAuthorized;
        return;
    }

    // 2. Der ausdrückliche Zielcontainer muss existieren.
    NSError *error = nil;
    if (containerIdentifier.length == 0
        || !ops.containerExists(containerIdentifier, &error)) {
        out->outcome = JCContactsCreateOutcomeContainerNotFound;
        if (error != nil) {
            JCCreateSanitizeDomain(error.domain.UTF8String, out->error_domain);
            out->error_code = error.code;
        }
        return;
    }

    // 3. Lesestapel-Preflight: scheitert er, gibt es keinen Save.
    error = nil;
    if (!ops.probeFetch(&error)) {
        out->outcome = JCContactsCreateOutcomeReadPreflightFailed;
        if (error != nil) {
            JCCreateSanitizeDomain(error.domain.UTF8String, out->error_domain);
            out->error_code = error.code;
        }
        return;
    }

    // 4. Genau ein Kontakt aus der freigegebenen Nutzlast.
    CNMutableContact *neu = JCCreateBuildContact(payload);
    if (neu == nil) {
        out->outcome = JCContactsCreateOutcomeInvalidPayload;
        return;
    }

    // 5. Genau ein Save, in der @try/@catch-Grenze.
    JCCreatePrepareDiag();
    JCCreateWriteSaveMarker("create");
    NSString *kennung = nil;
    @try {
        error = nil;
        out->add_request_count = 1;
        out->save_attempts = 1;
        kennung = ops.save(neu, containerIdentifier, transactionAuthor, &error);
        if (kennung == nil) {
            out->outcome = JCContactsCreateOutcomeSaveError;
            if (error != nil) {
                JCCreateSanitizeDomain(error.domain.UTF8String,
                                       out->error_domain);
                out->error_code = error.code;
            } else {
                strlcpy(out->error_domain, "JCContactsCreate",
                        sizeof(out->error_domain));
                out->error_code = -1;
            }
            JCCreateDiscardDiag();
            return;
        }
    }
    @catch (NSException *exception) {
        // Nach einem Wurf **im** Save ist unbekannt, ob geschrieben wurde.
        // Es gibt hier keinen zweiten Versuch — nie.
        out->outcome = JCContactsCreateOutcomeCaughtException;
        JCCreateSanitizeName(exception.name.UTF8String, out->exception_name);
        const char *reason = exception.reason.UTF8String;
        out->reason_present = (reason != NULL);
        const char *digestPtr = NULL;
        if (reason != NULL) {
            JCCreateSha256Hex(reason, strlen(reason), out->reason_digest);
            digestPtr = out->reason_digest;
        }
        out->diagnostics_artifact_written = JCCreateCommitDiag(
            "create-catch", out->exception_name, reason, digestPtr);
        return;
    }
    JCCreateDiscardDiag();

    if (kennung.length == 0 || kennung.length >= JC_CREATE_IDENTIFIER_CAPACITY) {
        // Gespeichert, aber ohne brauchbare Kennung: der Ausgang ist ungewiss.
        out->outcome = JCContactsCreateOutcomeIdentifierMissing;
        return;
    }
    out->provider_identifier_present = 1;
    strlcpy(out->provider_identifier, kennung.UTF8String,
            sizeof(out->provider_identifier));
    JCCreateSha256Hex(kennung.UTF8String, strlen(kennung.UTF8String),
                      out->provider_identifier_digest);

    // 6. Read-back über genau diese Kennung.
    NSDictionary *gelesen = ops.readback(kennung);
    if (gelesen == nil) {
        out->outcome = JCContactsCreateOutcomeReadbackFailed;
        return;
    }
    NSError *jsonFehler = nil;
    NSData *daten = [NSJSONSerialization dataWithJSONObject:gelesen
                                                    options:0
                                                      error:&jsonFehler];
    if (daten == nil || daten.length >= JC_CREATE_READBACK_CAPACITY) {
        out->outcome = JCContactsCreateOutcomeReadbackFailed;
        return;
    }
    memcpy(out->readback_json, daten.bytes, daten.length);
    out->readback_json[daten.length] = '\0';
    out->readback_succeeded = 1;
    out->outcome = JCContactsCreateOutcomeApplied;
}

// ── Produktivanbindung: echter CNContactStore ───────────────────────────────

/// Hängt die Persistenz-Stores an — **bevor** irgendetwas geschrieben wird.
///
/// **Warum das eine eigene Funktion ist (2026-08-04).** Der Helfer-Spike
/// starb mit `NSInternalInconsistencyException: This
/// NSPersistentStoreCoordinator has no persistent stores` — wortgleich zu
/// den vier CLI-Sidecar-Abstürzen. Die Lehre ist nicht „App-Prozess sicher,
/// Sidecar unsicher", sondern: **ein Prozess, der noch nie wirklich gelesen
/// hat, kann nicht speichern.** Der frühere Preflight suchte eine erfundene
/// Kennung; ein solcher Fetch findet nichts und rührt die Stores offenbar
/// nicht an.
///
/// Zwei echte Lesevorgänge, beide read-only, in dieser Reihenfolge:
///
/// 1. Das **volle** Container-Inventar (`predicate:nil`) — genau das tat der
///    AppSave-Spike, der auf diesem Gerät gelang.
/// 2. Eine **echte** Enumeration im Zielcontainer, abgebrochen nach dem
///    ersten Datensatz. Sie muss den Store tatsächlich öffnen; ein leeres
///    Ergebnis ist zulässig (ein leerer Container ist kein Fehler), ein
///    Fehler beim Aufzählen dagegen nicht.
///
/// Schlägt einer der beiden fehl, gibt es **keinen** Save.
static BOOL JCCreateWarmUpStores(CNContactStore *store,
                                 NSString *containerIdentifier,
                                 NSError *__autoreleasing *error) {
    NSArray<CNContainer *> *alle =
        [store containersMatchingPredicate:nil error:error];
    if (alle == nil) { return NO; }

    CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
        initWithKeysToFetch:@[ CNContactIdentifierKey ]];
    req.unifyResults = NO;
    req.mutableObjects = NO;
    if (containerIdentifier.length > 0) {
        req.predicate = [CNContact predicateForContactsInContainerWithIdentifier:
                            containerIdentifier];
    }
    return [store enumerateContactsWithFetchRequest:req error:error
                                         usingBlock:
        ^(CNContact *contact, BOOL *stop) { *stop = YES; }];
}

static JCCreateOps *JCCreateRealOps(NSString *zielcontainer) {
    // GENAU EIN produktiver CNContactStore je Lauf; dieselbe Instanz trägt
    // Containerprüfung, Preflight, Save und Read-back.
    CNContactStore *store = [[CNContactStore alloc] init];
    JCCreateOps *ops = [[JCCreateOps alloc] init];

    ops.authorization = ^JCCreateAuth {
        return ([CNContactStore authorizationStatusForEntityType:
                    CNEntityTypeContacts] == CNAuthorizationStatusAuthorized)
            ? JCCreateAuthAuthorized : JCCreateAuthNotAuthorized;
    };

    ops.containerExists = ^BOOL(NSString *identifier,
                                NSError *__autoreleasing *error) {
        NSArray<CNContainer *> *treffer = [store
            containersMatchingPredicate:
                [CNContainer predicateForContainersWithIdentifiers:@[ identifier ]]
                                  error:error];
        return treffer != nil && treffer.count == 1;
    };

    ops.probeFetch = ^BOOL(NSError *__autoreleasing *error) {
        return JCCreateWarmUpStores(store, zielcontainer, error);
    };

    ops.save = ^NSString *_Nullable(CNMutableContact *kontakt,
                                    NSString *containerIdentifier,
                                    NSString *transactionAuthor,
                                    NSError *__autoreleasing *error) {
        CNSaveRequest *req = [[CNSaveRequest alloc] init];
        if (@available(macOS 12.0, *)) {
            if (transactionAuthor.length > 0) {
                req.transactionAuthor = transactionAuthor;
            }
        }
        [req addContact:kontakt toContainerWithIdentifier:containerIdentifier];
        BOOL ok = [store executeSaveRequest:req error:error];
        return ok ? kontakt.identifier : nil;
    };

    ops.readback = ^NSDictionary *_Nullable(NSString *providerIdentifier) {
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:JCCreateReadbackKeys()];
        req.unifyResults = NO;
        req.mutableObjects = NO;
        req.predicate = [CNContact
            predicateForContactsWithIdentifiers:@[ providerIdentifier ]];
        __block NSDictionary *projektion = nil;
        __block NSInteger treffer = 0;
        NSError *fehler = nil;
        BOOL ok = [store enumerateContactsWithFetchRequest:req
                                                     error:&fehler
                                                usingBlock:
            ^(CNContact *contact, BOOL *stop) {
                treffer += 1;
                projektion = JCCreateProject(contact);
                *stop = YES;
            }];
        return (ok && treffer == 1) ? projektion : nil;
    };

    return ops;
}

// ── Kontaktfreie Anbindung: Fakes, kein Store ───────────────────────────────

static JCCreateOps *JCCreateFakeOps(int32_t scenario) {
    JCCreateOps *ops = [[JCCreateOps alloc] init];
    __block CNMutableContact *gespeichert = nil;

    ops.authorization = ^JCCreateAuth {
        return (scenario == JCCreateScenarioNotAuthorized)
            ? JCCreateAuthNotAuthorized : JCCreateAuthAuthorized;
    };
    ops.containerExists = ^BOOL(NSString *identifier,
                                NSError *__autoreleasing *error) {
        return scenario != JCCreateScenarioContainerMissing;
    };
    ops.probeFetch = ^BOOL(NSError *__autoreleasing *error) {
        if (scenario == JCCreateScenarioFetchFails) {
            if (error != NULL) {
                *error = [NSError errorWithDomain:@"JCCreateFake" code:42
                                         userInfo:nil];
            }
            return NO;
        }
        return YES;
    };
    ops.save = ^NSString *_Nullable(CNMutableContact *kontakt,
                                    NSString *containerIdentifier,
                                    NSString *transactionAuthor,
                                    NSError *__autoreleasing *error) {
        if (scenario == JCCreateScenarioSaveNSError) {
            if (error != NULL) {
                *error = [NSError errorWithDomain:@"JCCreateFake" code:7
                                         userInfo:nil];
            }
            return nil;
        }
        if (scenario == JCCreateScenarioSaveThrows) {
            @throw [NSException exceptionWithName:@"JCCreateFakeException"
                                           reason:@"synthetischer Wurf"
                                         userInfo:nil];
        }
        gespeichert = kontakt;
        if (scenario == JCCreateScenarioIdentifierMissing) { return @""; }
        return @"FAKE-PROVIDER-IDENTIFIER-0001";
    };
    ops.readback = ^NSDictionary *_Nullable(NSString *providerIdentifier) {
        if (scenario == JCCreateScenarioReadbackMissing) { return nil; }
        if (gespeichert == nil) { return nil; }
        NSDictionary *projektion = JCCreateProject(gespeichert);
        if (scenario == JCCreateScenarioReadbackDiffers) {
            NSMutableDictionary *abweichend = [projektion mutableCopy];
            abweichend[@"givenName"] = @"Abweichend";
            return abweichend;
        }
        return projektion;
    };
    return ops;
}

// ── C-Einstiege ─────────────────────────────────────────────────────────────

static NSDictionary *_Nullable JCCreateParsePayload(const char *payload_json) {
    if (payload_json == NULL) { return nil; }
    NSData *daten = [NSData dataWithBytes:payload_json
                                   length:strlen(payload_json)];
    id wert = [NSJSONSerialization JSONObjectWithData:daten options:0
                                                error:NULL];
    return [wert isKindOfClass:NSDictionary.class] ? wert : nil;
}

void jc_contacts_create_run(const char *payload_json,
                            const char *container_identifier,
                            const char *transaction_author,
                            JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *payload = JCCreateParsePayload(payload_json);
        if (payload == nil) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsCreateOutcomeInvalidPayload;
            return;
        }
        NSString *container = container_identifier
            ? @(container_identifier) : @"";
        NSString *autor = transaction_author ? @(transaction_author) : @"";
        JCCreateRun(JCCreateRealOps(container), payload, container, autor, out);
    }
}

void jc_contacts_create_run_scenario(int32_t scenario,
                                     const char *payload_json,
                                     JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *payload = JCCreateParsePayload(payload_json);
        if (payload == nil) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsCreateOutcomeInvalidPayload;
            return;
        }
        JCCreateRun(JCCreateFakeOps(scenario), payload,
                    @"FAKE-CONTAINER", @"de.kluender.jarvis.contacts-bridge",
                    out);
    }
}

// ═══ Update und Delete (ADR-0026 §8.2/§8.3, DEC-053) ════════════════════════
//
// Derselbe Aufbau wie beim Create: ein Operationsobjekt trennt Ablauf und
// Store-Anbindung, der Ablauf existiert genau einmal. Was hinzukommt, ist
// der **Vorher-Vergleich**: gelesen wird unmittelbar vor dem Save, und
// verglichen wird strukturell gegen den Zustand, den der Mensch freigegeben
// hat. Kein Digest in Objective-C — `isEqualToDictionary:` auf zwei
// Projektionen ist strenger als ein Hash und braucht keine zweite
// Kanonisierung, die auseinanderlaufen könnte.

typedef NS_ENUM(int32_t, JCWriteKind) { JCWriteKindUpdate = 1,
                                        JCWriteKindDelete = 2 };

@interface JCWriteOps : NSObject
@property (nonatomic, copy) JCCreateAuth (^authorization)(void);
/// Liest das Ziel **über den Identifier**. `*lesbar` unterscheidet
/// „nicht vorhanden" von „nicht lesbar" — der Unterschied entscheidet
/// zwischen Konflikt und ungewissem Ausgang.
@property (nonatomic, copy) CNContact *_Nullable (^fetchTarget)
    (NSString *identifier, BOOL *lesbar);
/// Identifier der Me-Karte, oder `nil`. Ein Fehler beim Lesen ergibt `nil`
/// **und** setzt `*bekannt` auf NO — dann wird nicht gelöscht.
@property (nonatomic, copy) NSString *_Nullable (^meCardIdentifier)(BOOL *bekannt);
/// Container des Ziels, oder `nil`.
@property (nonatomic, copy) NSString *_Nullable (^containerOf)(NSString *identifier);
/// GENAU EIN Save. `kind` entscheidet Update oder Delete.
@property (nonatomic, copy) BOOL (^save)(CNMutableContact *kontakt,
                                         JCWriteKind kind,
                                         NSError *__autoreleasing *error);
/// Read-back über den Identifier. `*vorhanden` sagt, ob überhaupt etwas kam.
@property (nonatomic, copy) NSDictionary *_Nullable (^readback)
    (NSString *identifier, BOOL *lesbar, BOOL *vorhanden);
@end

@implementation JCWriteOps
@end

/// Setzt **nur** die benannten Felder auf der `mutableCopy`.
///
/// Die drei Fälle sind bewusst getrennt: Ein fehlender Schlüssel rührt das
/// Feld nicht an, `null` beziehungsweise `[]` löscht es ausdrücklich, ein
/// Wert ersetzt es. Alles, was v1 nicht kennt — Notiz, Bild, Beziehungen —
/// trägt die Kopie unverändert weiter; genau dafür gibt es sie.
static BOOL JCWriteApplyPatch(CNMutableContact *ziel, NSDictionary *patch) {
    NSArray *erlaubt = JCCreateAllowedKeys();
    for (NSString *schluessel in patch) {
        if (![erlaubt containsObject:schluessel]) { return NO; }
    }
    if (patch[@"contactType"] != nil) {
        // Typwechsel ist in v1 nicht zugesagt (ADR-0026 §7).
        return NO;
    }

    NSDictionary *skalare = JCCreateScalarKeys();
    for (NSString *schluessel in skalare) {
        id wert = patch[schluessel];
        if (wert == nil) { continue; }
        if (wert == NSNull.null) {
            [ziel setValue:@"" forKey:skalare[schluessel]];
        } else if ([wert isKindOfClass:NSString.class]) {
            [ziel setValue:wert forKey:skalare[schluessel]];
        } else {
            return NO;
        }
    }

    id geburtstag = patch[@"birthday"];
    if (geburtstag == NSNull.null) {
        ziel.birthday = nil;
    } else if ([geburtstag isKindOfClass:NSDictionary.class]) {
        NSDateComponents *k = JCCreateComponents(geburtstag);
        if (k == nil) { return NO; }
        ziel.birthday = k;
    } else if (geburtstag != nil) {
        return NO;
    }

    // Listen: Ersatz der ganzen benannten Liste, `[]` löscht alle Werte.
    if (!JCCreateApplyLists(ziel, patch, YES)) { return NO; }
    return YES;
}

/// Der eine Ablauf für Update und Delete.
static void JCWriteRun(JCWriteOps *ops, JCWriteKind kind,
                       NSString *identifier, NSDictionary *_Nullable patch,
                       NSDictionary *erwartetVorher,
                       NSString *_Nullable erwarteterContainer,
                       JCContactsCreateResult *out) {
    memset(out, 0, sizeof(*out));
    JCCreateInstallUncaught();

    if (ops.authorization() != JCCreateAuthAuthorized) {
        out->outcome = JCContactsWriteOutcomeNotAuthorized;
        return;
    }

    // 1. Unmittelbarer Read über den Identifier — nie über einen Namen.
    BOOL lesbar = NO;
    CNContact *gelesen = ops.fetchTarget(identifier, &lesbar);
    if (!lesbar) {
        // Nicht lesbar ist **kein** Befund über die Existenz.
        out->outcome = JCContactsWriteOutcomeReadbackFailed;
        return;
    }
    if (gelesen == nil) {
        out->outcome = JCContactsWriteOutcomeTargetNotFound;
        return;
    }

    // 2. Der Zustand muss der sein, den der Mensch freigegeben hat.
    NSDictionary *ist = JCCreateProject(gelesen);
    if (![ist isEqualToDictionary:erwartetVorher]) {
        out->outcome = JCContactsWriteOutcomeRevisionConflict;
        return;
    }

    if (kind == JCWriteKindDelete) {
        // 3a. Me-Karte ist nie ein Mutationsziel. Unbekannt heisst nein.
        BOOL meBekannt = NO;
        NSString *meCard = ops.meCardIdentifier(&meBekannt);
        if (!meBekannt) {
            out->outcome = JCContactsWriteOutcomeMeCardProtected;
            return;
        }
        if (meCard != nil && [meCard isEqualToString:identifier]) {
            out->outcome = JCContactsWriteOutcomeMeCardProtected;
            return;
        }
        // 3b. Containerbindung: gelöscht wird nur im erwarteten Container.
        if (erwarteterContainer.length > 0) {
            NSString *ist_container = ops.containerOf(identifier);
            if (ist_container == nil
                || ![ist_container isEqualToString:erwarteterContainer]) {
                out->outcome = JCContactsWriteOutcomeContainerMismatch;
                return;
            }
        }
    }

    CNMutableContact *kopie = [gelesen mutableCopy];
    if (kind == JCWriteKindUpdate && !JCWriteApplyPatch(kopie, patch)) {
        out->outcome = JCContactsWriteOutcomeInvalidPayload;
        return;
    }

    // 4. Genau ein Save, in der @try/@catch-Grenze.
    JCCreatePrepareDiag();
    JCCreateWriteSaveMarker(kind == JCWriteKindUpdate ? "update" : "delete");
    @try {
        NSError *fehler = nil;
        BOOL ok = ops.save(kopie, kind, &fehler);
        out->save_attempts = 1;
        out->add_request_count = 1;      // ein Update- bzw. Delete-Request
        if (!ok) {
            out->outcome = JCContactsWriteOutcomeSaveError;
            if (fehler != nil) {
                JCCreateSanitizeDomain(fehler.domain.UTF8String,
                                       out->error_domain);
                out->error_code = fehler.code;
            }
            JCCreateDiscardDiag();
            return;
        }
    }
    @catch (NSException *ausnahme) {
        out->save_attempts = 1;
        out->add_request_count = 1;
        out->outcome = JCContactsWriteOutcomeCaughtException;
        JCCreateSanitizeName(ausnahme.name.UTF8String, out->exception_name);
        const char *grund = ausnahme.reason.UTF8String;
        out->reason_present = (grund != NULL);
        const char *digest = NULL;
        if (grund != NULL) {
            JCCreateSha256Hex(grund, strlen(grund), out->reason_digest);
            digest = out->reason_digest;
        }
        out->diagnostics_artifact_written = JCCreateCommitDiag(
            "contacts-write-catch", out->exception_name, grund, digest);
        return;
    }
    JCCreateDiscardDiag();

    // 5. Beleg über **genau diese** Kennung.
    strlcpy(out->provider_identifier, identifier.UTF8String,
            sizeof(out->provider_identifier));
    JCCreateSha256Hex(identifier.UTF8String, strlen(identifier.UTF8String),
                      out->provider_identifier_digest);
    out->provider_identifier_present = 1;

    BOOL nachLesbar = NO, vorhanden = NO;
    NSDictionary *nachher = ops.readback(identifier, &nachLesbar, &vorhanden);

    if (kind == JCWriteKindDelete) {
        if (!nachLesbar) {
            // Nicht lesbar ist kein Löschbeweis (ADR-0026 §8.3).
            out->outcome = JCContactsWriteOutcomeAbsenceUnproven;
            return;
        }
        if (vorhanden) {
            out->outcome = JCContactsWriteOutcomeAbsenceUnproven;
            return;
        }
        out->readback_succeeded = 1;
        out->outcome = JCContactsWriteOutcomeApplied;
        strlcpy(out->readback_json, "{}", sizeof(out->readback_json));
        return;
    }

    if (!nachLesbar || !vorhanden || nachher == nil) {
        out->outcome = JCContactsWriteOutcomeReadbackFailed;
        return;
    }
    NSError *jsonFehler = nil;
    NSData *daten = [NSJSONSerialization dataWithJSONObject:nachher
                                                    options:0
                                                      error:&jsonFehler];
    if (daten == nil || daten.length >= JC_CREATE_READBACK_CAPACITY) {
        out->outcome = JCContactsWriteOutcomeReadbackFailed;
        return;
    }
    memcpy(out->readback_json, daten.bytes, daten.length);
    out->readback_json[daten.length] = '\0';
    out->readback_succeeded = 1;
    out->outcome = JCContactsWriteOutcomeApplied;
}

// ── Produktivanbindung ──────────────────────────────────────────────────────

static JCWriteOps *JCWriteRealOps(NSString *autor) {
    CNContactStore *store = [[CNContactStore alloc] init];
    JCWriteOps *ops = [[JCWriteOps alloc] init];

    ops.authorization = ^JCCreateAuth {
        return ([CNContactStore authorizationStatusForEntityType:
                    CNEntityTypeContacts] == CNAuthorizationStatusAuthorized)
            ? JCCreateAuthAuthorized : JCCreateAuthNotAuthorized;
    };

    ops.fetchTarget = ^CNContact *_Nullable(NSString *identifier, BOOL *lesbar) {
        // Erst die Stores anhaengen — ein frischer Prozess kann sonst nicht
        // speichern (Beleg: Helfer-Spike 2026-08-04). Ohne Warmlauf gilt das
        // Ziel als nicht lesbar, und das endet vor jeder Uebergabe.
        NSError *warm = nil;
        if (!JCCreateWarmUpStores(store, nil, &warm)) {
            *lesbar = NO;
            return nil;
        }
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:JCCreateReadbackKeys()];
        req.unifyResults = NO;
        req.mutableObjects = YES;      // die Kopie traegt ungelesene Keys weiter
        req.predicate =
            [CNContact predicateForContactsWithIdentifiers:@[ identifier ]];
        __block CNContact *treffer = nil;
        NSError *fehler = nil;
        BOOL ok = [store enumerateContactsWithFetchRequest:req error:&fehler
                                                usingBlock:
            ^(CNContact *contact, BOOL *stop) { treffer = contact; *stop = YES; }];
        *lesbar = ok;
        return ok ? treffer : nil;
    };

    ops.meCardIdentifier = ^NSString *_Nullable(BOOL *bekannt) {
        NSError *fehler = nil;
        CNContact *me = [store unifiedMeContactWithKeysToFetch:
                             @[ CNContactIdentifierKey ] error:&fehler];
        if (me == nil && fehler != nil
            && fehler.code != CNErrorCodeRecordDoesNotExist) {
            *bekannt = NO;          // unklar — dann wird nicht geloescht
            return nil;
        }
        *bekannt = YES;
        return me.identifier;
    };

    ops.containerOf = ^NSString *_Nullable(NSString *identifier) {
        NSError *fehler = nil;
        NSArray<CNContainer *> *treffer = [store containersMatchingPredicate:
            [CNContainer predicateForContainerOfContactWithIdentifier:identifier]
                                                                       error:&fehler];
        return treffer.count == 1 ? treffer.firstObject.identifier : nil;
    };

    ops.save = ^BOOL(CNMutableContact *kontakt, JCWriteKind kind,
                     NSError *__autoreleasing *error) {
        CNSaveRequest *req = [[CNSaveRequest alloc] init];
        if (@available(macOS 12.0, *)) { req.transactionAuthor = autor; }
        if (kind == JCWriteKindUpdate) {
            [req updateContact:kontakt];
        } else {
            [req deleteContact:kontakt];
        }
        return [store executeSaveRequest:req error:error];
    };

    ops.readback = ^NSDictionary *_Nullable(NSString *identifier,
                                            BOOL *lesbar, BOOL *vorhanden) {
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:JCCreateReadbackKeys()];
        req.unifyResults = NO;
        req.mutableObjects = NO;
        req.predicate =
            [CNContact predicateForContactsWithIdentifiers:@[ identifier ]];
        __block NSDictionary *projektion = nil;
        __block BOOL gefunden = NO;
        NSError *fehler = nil;
        BOOL ok = [store enumerateContactsWithFetchRequest:req error:&fehler
                                                usingBlock:
            ^(CNContact *contact, BOOL *stop) {
                gefunden = YES;
                projektion = JCCreateProject(contact);
                *stop = YES;
            }];
        *lesbar = ok;
        *vorhanden = gefunden;
        return projektion;
    };
    return ops;
}

static NSDictionary *_Nullable JCWriteParse(const char *json) {
    if (json == NULL) { return nil; }
    NSData *daten = [NSData dataWithBytes:json length:strlen(json)];
    id wert = [NSJSONSerialization JSONObjectWithData:daten options:0 error:NULL];
    return [wert isKindOfClass:NSDictionary.class] ? wert : nil;
}

void jc_contacts_update_run(const char *provider_identifier,
                            const char *patch_json,
                            const char *expected_previous_json,
                            const char *transaction_author,
                            JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *patch = JCWriteParse(patch_json);
        NSDictionary *vorher = JCWriteParse(expected_previous_json);
        if (patch == nil || vorher == nil || provider_identifier == NULL) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsWriteOutcomeInvalidPayload;
            return;
        }
        NSString *autor = transaction_author
            ? @(transaction_author) : @"de.kluender.jarvis.contacts-bridge";
        JCWriteRun(JCWriteRealOps(autor), JCWriteKindUpdate,
                   @(provider_identifier), patch, vorher, nil, out);
    }
}

void jc_contacts_delete_run(const char *provider_identifier,
                            const char *expected_previous_json,
                            const char *expected_container,
                            const char *transaction_author,
                            JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *vorher = JCWriteParse(expected_previous_json);
        if (vorher == nil || provider_identifier == NULL) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsWriteOutcomeInvalidPayload;
            return;
        }
        NSString *autor = transaction_author
            ? @(transaction_author) : @"de.kluender.jarvis.contacts-bridge";
        NSString *container = (expected_container && *expected_container)
            ? @(expected_container) : nil;
        JCWriteRun(JCWriteRealOps(autor), JCWriteKindDelete,
                   @(provider_identifier), nil, vorher, container, out);
    }
}

// ── Kontaktfreier Testeinstieg für Update und Delete ────────────────────────
//
// Derselbe Ablauf, andere Anbindung: kein `CNContactStore`, kein
// Store-Zugriff, kein TCC-Dialog. Der Zielkontakt entsteht aus dem
// erwarteten Vorzustand — damit prüft der Test denselben Vergleich, den
// der Produktivpfad ausführt, statt einen nachgebauten.

static JCWriteOps *JCWriteFakeOps(int32_t szenario, NSDictionary *vorher,
                                  __strong NSMutableDictionary **spur) {
    JCWriteOps *ops = [[JCWriteOps alloc] init];
    NSMutableDictionary *zaehler = *spur;

    ops.authorization = ^JCCreateAuth {
        return (szenario == JCWriteScenarioNotAuthorized)
            ? JCCreateAuthNotAuthorized : JCCreateAuthAuthorized;
    };

    ops.fetchTarget = ^CNContact *_Nullable(NSString *identifier, BOOL *lesbar) {
        if (szenario == JCWriteScenarioReadUnavailable) { *lesbar = NO; return nil; }
        *lesbar = YES;
        if (szenario == JCWriteScenarioTargetMissing) { return nil; }
        NSDictionary *quelle = vorher;
        if (szenario == JCWriteScenarioRevisionConflict) {
            NSMutableDictionary *abweichend = [vorher mutableCopy];
            abweichend[@"jobTitle"] = @"fremd geaendert";
            quelle = abweichend;
        }
        return JCCreateBuildContact(quelle);
    };

    ops.meCardIdentifier = ^NSString *_Nullable(BOOL *bekannt) {
        *bekannt = YES;
        return (szenario == JCWriteScenarioMeCard) ? @"ZIEL" : @"jemand-anders";
    };

    ops.containerOf = ^NSString *_Nullable(NSString *identifier) {
        return (szenario == JCWriteScenarioContainerMismatch)
            ? @"anderer-container" : @"erwarteter-container";
    };

    ops.save = ^BOOL(CNMutableContact *kontakt, JCWriteKind kind,
                     NSError *__autoreleasing *error) {
        zaehler[@"saves"] = @([zaehler[@"saves"] intValue] + 1);
        if (szenario == JCWriteScenarioSaveNSError) {
            if (error) {
                *error = [NSError errorWithDomain:@"JCFake" code:42 userInfo:nil];
            }
            return NO;
        }
        if (szenario == JCWriteScenarioSaveThrows) {
            @throw [NSException exceptionWithName:@"JCFakeException"
                                           reason:@"synthetisch" userInfo:nil];
        }
        // Nach einem Delete gibt es nichts mehr zu lesen — genau das ist
        // der Beleg, den der Ablauf danach verlangt.
        if (kind == JCWriteKindUpdate) {
            zaehler[@"kontakt"] = JCCreateProject(kontakt);
        } else {
            [zaehler removeObjectForKey:@"kontakt"];
        }
        return YES;
    };

    ops.readback = ^NSDictionary *_Nullable(NSString *identifier,
                                            BOOL *lesbar, BOOL *vorhanden) {
        if (szenario == JCWriteScenarioReadbackMissing) {
            *lesbar = NO; *vorhanden = NO; return nil;
        }
        if (szenario == JCWriteScenarioStillPresent) {
            *lesbar = YES; *vorhanden = YES; return zaehler[@"kontakt"] ?: vorher;
        }
        *lesbar = YES;
        NSDictionary *ergebnis = zaehler[@"kontakt"];
        *vorhanden = (ergebnis != nil);
        return ergebnis;
    };
    return ops;
}

void jc_contacts_update_run_scenario(int32_t szenario, const char *patch_json,
                                     const char *expected_previous_json,
                                     JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *patch = JCWriteParse(patch_json);
        NSDictionary *vorher = JCWriteParse(expected_previous_json);
        if (patch == nil || vorher == nil) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsWriteOutcomeInvalidPayload;
            return;
        }
        NSMutableDictionary *spur = [NSMutableDictionary dictionary];
        JCWriteRun(JCWriteFakeOps(szenario, vorher, &spur), JCWriteKindUpdate,
                   @"ZIEL", patch, vorher, nil, out);
    }
}

void jc_contacts_delete_run_scenario(int32_t szenario,
                                     const char *expected_previous_json,
                                     JCContactsCreateResult *out) {
    @autoreleasepool {
        NSDictionary *vorher = JCWriteParse(expected_previous_json);
        if (vorher == nil) {
            memset(out, 0, sizeof(*out));
            out->outcome = JCContactsWriteOutcomeInvalidPayload;
            return;
        }
        NSMutableDictionary *spur = [NSMutableDictionary dictionary];
        // Delete meldet Abwesenheit; der Fake liefert nach dem Save nichts
        // mehr zurueck, ausser das Szenario verlangt ausdruecklich anderes.
        JCWriteRun(JCWriteFakeOps(szenario, vorher, &spur), JCWriteKindDelete,
                   @"ZIEL", nil, vorher, @"erwarteter-container", out);
    }
}

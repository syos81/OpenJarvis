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
//  Feldabbildung: ausschliesslich der eingefrorene v1-Vertrag (ADR-0020 §7).
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

    // Etikettierte Listen — Reihenfolge ist Position, keine Sortierung.
    NSArray *mails = payload[@"emails"];
    if (mails != nil && mails != NSNull.null) {
        if (![mails isKindOfClass:NSArray.class]) { return nil; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *e in mails) {
            if (![e isKindOfClass:NSDictionary.class]) { return nil; }
            NSString *v = e[@"value"];
            if (![v isKindOfClass:NSString.class]) { return nil; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(e[@"label"]) value:v]];
        }
        neu.emailAddresses = werte;
    }

    NSArray *rufnummern = payload[@"phones"];
    if (rufnummern != nil && rufnummern != NSNull.null) {
        if (![rufnummern isKindOfClass:NSArray.class]) { return nil; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *p in rufnummern) {
            if (![p isKindOfClass:NSDictionary.class]) { return nil; }
            NSString *v = p[@"value"];
            if (![v isKindOfClass:NSString.class]) { return nil; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(p[@"label"])
                        value:[CNPhoneNumber phoneNumberWithStringValue:v]]];
        }
        neu.phoneNumbers = werte;
    }

    NSArray *adressen = payload[@"postalAddresses"];
    if (adressen != nil && adressen != NSNull.null) {
        if (![adressen isKindOfClass:NSArray.class]) { return nil; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *a in adressen) {
            if (![a isKindOfClass:NSDictionary.class]) { return nil; }
            CNMutablePostalAddress *pa = [[CNMutablePostalAddress alloc] init];
            NSDictionary *teile = @{ @"street": @"street", @"city": @"city",
                                     @"state": @"state",
                                     @"postalCode": @"postalCode",
                                     @"country": @"country",
                                     @"isoCountryCode": @"ISOCountryCode" };
            for (NSString *k in teile) {
                id v = a[k];
                if (v == nil || v == NSNull.null) { continue; }
                if (![v isKindOfClass:NSString.class]) { return nil; }
                [pa setValue:v forKey:teile[k]];
            }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(a[@"label"]) value:pa]];
        }
        neu.postalAddresses = werte;
    }

    NSArray *adressenWeb = payload[@"urls"];
    if (adressenWeb != nil && adressenWeb != NSNull.null) {
        if (![adressenWeb isKindOfClass:NSArray.class]) { return nil; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *u in adressenWeb) {
            if (![u isKindOfClass:NSDictionary.class]) { return nil; }
            NSString *v = u[@"value"];
            if (![v isKindOfClass:NSString.class]) { return nil; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(u[@"label"]) value:v]];
        }
        neu.urlAddresses = werte;
    }

    NSArray *daten = payload[@"dates"];
    if (daten != nil && daten != NSNull.null) {
        if (![daten isKindOfClass:NSArray.class]) { return nil; }
        NSMutableArray *werte = [NSMutableArray array];
        for (NSDictionary *d in daten) {
            if (![d isKindOfClass:NSDictionary.class]) { return nil; }
            NSDateComponents *k = JCCreateComponents(d);
            if (k == nil) { return nil; }
            [werte addObject:[[CNLabeledValue alloc]
                initWithLabel:JCCreateCNLabel(d[@"label"]) value:k]];
        }
        neu.dates = werte;
    }

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

static JCCreateOps *JCCreateRealOps(void) {
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
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:@[ CNContactIdentifierKey ]];
        req.unifyResults = NO;
        req.mutableObjects = NO;
        NSString *probe = [NSString stringWithFormat:@"JC-CREATE-PROBE-%@",
                           NSUUID.UUID.UUIDString];
        req.predicate =
            [CNContact predicateForContactsWithIdentifiers:@[ probe ]];
        return [store enumerateContactsWithFetchRequest:req
                                                  error:error
                                             usingBlock:
            ^(CNContact *contact, BOOL *stop) { *stop = YES; }];
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
        JCCreateRun(JCCreateRealOps(), payload, container, autor, out);
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

//  JCContactsAppSaveSpike.m — App-Prozess-Save-Spike.
//
//  Umsetzung des Vertrags aus JCContactsAppSaveSpike.h. Aufbau:
//
//  1. Ein Operationsobjekt (Blocks) trennt den Ablauf von der Store-Anbindung:
//     der Produktivpfad füllt es mit echten CNContactStore-Aufrufen, der
//     kontaktfreie Testeinstieg mit Fakes. Der Ablauf selbst ist EINE Funktion
//     — es gibt keinen zweiten Weg zum Save.
//  2. Der Save läuft in einer Objective-C-@try/@catch-Grenze; zusätzlich ist
//     die Uncaught-Letztdiagnose installiert (der Dispatch-Wurf des Sidecars
//     erreichte kein @catch — Crashreport-Beleg 2026-08-02).
//  3. Der Roh-Reason existiert nur im Diagnoseartefakt
//     (OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH, Ordner 0700, Datei
//     exklusiv 0600); öffentlich reisen nur Klassenname und SHA-256-Digest.

#import "JCContactsAppSaveSpike.h"

#import <Contacts/Contacts.h>
#import <CommonCrypto/CommonDigest.h>
#import <sys/stat.h>
#import <sys/utsname.h>
#import <fcntl.h>
#import <unistd.h>
#import <string.h>

// ── Fester Spike-Vertrag ─────────────────────────────────────────────────────

/// Fester Payload — nicht konfigurierbar, kommt nie aus dem Frontend.
static NSString *const kSpikeGivenName = @"ZZZ-JarvisTest-AppSave";

/// Kanonischer Transaktionsautor — wortgleich zum Sidecar
/// (native/contacts-bridge/src/sidecar.swift: kTransactionAuthor), damit die
/// Echo-Unterdrückung des Lese-Syncs diesen Schreiber ausschließt.
static NSString *const kSpikeTransactionAuthor =
    @"de.kluender.jarvis.contacts-bridge";

static NSString *const kDiagnosticsEnvVar =
    @"OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH";

// ── C-nahe Hilfen (terminierungsfest, aus dem Sidecar-Shim übernommen) ──────

static void JCSpikeSha256Hex(const char *bytes, size_t len, char out[65]) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(bytes, (CC_LONG)len, digest);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        out[i * 2]     = hex[digest[i] >> 4];
        out[i * 2 + 1] = hex[digest[i] & 0x0F];
    }
    out[64] = '\0';
}

static void JCSpikeSanitizeName(const char *_Nullable name, char out[65]) {
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

static void JCSpikeSanitizeDomain(const char *_Nullable domain, char out[128]) {
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

// ── Diagnoseartefakt (Regeln unverändert: 0700-Ordner, 0600-Datei, exklusiv) ─

static struct {
    int  fd;
    long sequence;
    char arch[32];
    char os[32];
    double preparedAt;
} gSpikeDiag = { .fd = -1 };

static BOOL JCSpikeDiagDirUsable(NSString *dir) {
    if (dir.length == 0 || ![dir hasPrefix:@"/"]) { return NO; }
    struct stat st;
    if (lstat(dir.fileSystemRepresentation, &st) != 0) { return NO; }
    if (S_ISLNK(st.st_mode) || !S_ISDIR(st.st_mode)) { return NO; }
    if (st.st_uid != geteuid()) { return NO; }
    if ((st.st_mode & 0777) != 0700) { return NO; }
    return YES;
}

static void JCSpikeDiscardDiag(void) {
    if (gSpikeDiag.fd < 0) { return; }
    close(gSpikeDiag.fd);
    gSpikeDiag.fd = -1;
}

static char gSpikeDiagPath[1024];

static void JCSpikePrepareDiag(void) {
    if (gSpikeDiag.fd >= 0) {
        close(gSpikeDiag.fd);
        unlink(gSpikeDiagPath);
        gSpikeDiag.fd = -1;
    }
    NSString *dir = NSProcessInfo.processInfo.environment[kDiagnosticsEnvVar];
    if (dir == nil || !JCSpikeDiagDirUsable(dir)) { return; }

    struct utsname uts;
    strlcpy(gSpikeDiag.arch, uname(&uts) == 0 ? uts.machine : "unknown",
            sizeof(gSpikeDiag.arch));
    NSOperatingSystemVersion os =
        NSProcessInfo.processInfo.operatingSystemVersion;
    snprintf(gSpikeDiag.os, sizeof(gSpikeDiag.os), "%ld.%ld.%ld",
             (long)os.majorVersion, (long)os.minorVersion,
             (long)os.patchVersion);
    gSpikeDiag.preparedAt = [NSDate date].timeIntervalSince1970;
    static long seq = 0;
    gSpikeDiag.sequence = ++seq;

    NSString *name = [NSString stringWithFormat:
        @"contacts-app-spike-exception-%.0f-%d-%ld.json",
        gSpikeDiag.preparedAt * 1000.0, getpid(), gSpikeDiag.sequence];
    NSString *path = [dir stringByAppendingPathComponent:name];
    if (strlcpy(gSpikeDiagPath, path.fileSystemRepresentation,
                sizeof(gSpikeDiagPath)) >= sizeof(gSpikeDiagPath)) {
        return;
    }
    int fd = open(gSpikeDiagPath,
                  O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd >= 0) { gSpikeDiag.fd = fd; }
}

static void JCSpikeWriteLiteral(int fd, const char *s) {
    write(fd, s, strlen(s));
}

static void JCSpikeWriteJsonEscaped(int fd, const char *_Nullable s,
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

#define JC_SPIKE_REASON_MAX 4096

static BOOL JCSpikeCommitDiag(const char *source, const char name[65],
                              const char *_Nullable reasonUtf8,
                              const char *_Nullable digestHex) {
    if (gSpikeDiag.fd < 0) { return NO; }
    int fd = gSpikeDiag.fd;
    char zahl[64];
    JCSpikeWriteLiteral(fd, "{\"source\":\"");
    JCSpikeWriteLiteral(fd, source);
    JCSpikeWriteLiteral(fd, "\",\"preparedAt\":");
    snprintf(zahl, sizeof(zahl), "%.3f", gSpikeDiag.preparedAt);
    JCSpikeWriteLiteral(fd, zahl);
    JCSpikeWriteLiteral(fd, ",\"exceptionName\":\"");
    JCSpikeWriteJsonEscaped(fd, name, 64);
    JCSpikeWriteLiteral(fd, "\",\"reasonPresent\":");
    JCSpikeWriteLiteral(fd, reasonUtf8 ? "true" : "false");
    if (reasonUtf8 != NULL) {
        JCSpikeWriteLiteral(fd, ",\"reasonTruncated\":");
        JCSpikeWriteLiteral(fd,
            strlen(reasonUtf8) > JC_SPIKE_REASON_MAX ? "true" : "false");
        JCSpikeWriteLiteral(fd, ",\"reason\":\"");
        JCSpikeWriteJsonEscaped(fd, reasonUtf8, JC_SPIKE_REASON_MAX);
        JCSpikeWriteLiteral(fd, "\"");
    }
    if (digestHex != NULL) {
        JCSpikeWriteLiteral(fd, ",\"reasonDigest\":\"");
        JCSpikeWriteLiteral(fd, digestHex);
        JCSpikeWriteLiteral(fd, "\"");
    }
    JCSpikeWriteLiteral(fd, ",\"architecture\":\"");
    JCSpikeWriteJsonEscaped(fd, gSpikeDiag.arch, sizeof(gSpikeDiag.arch));
    JCSpikeWriteLiteral(fd, "\",\"osVersion\":\"");
    JCSpikeWriteJsonEscaped(fd, gSpikeDiag.os, sizeof(gSpikeDiag.os));
    JCSpikeWriteLiteral(fd, "\"}");
    BOOL ok = (fsync(fd) == 0);
    close(fd);
    gSpikeDiag.fd = -1;
    return ok;
}

// ── Uncaught-Letztdiagnose (Kette zum fremden Handler bleibt erhalten) ──────

static NSUncaughtExceptionHandler *gSpikePreviousHandler = NULL;
static BOOL gSpikeUncaughtInstalled = NO;

static void JCSpikeUncaughtHandler(NSException *exception) {
    char name[65];
    JCSpikeSanitizeName(exception.name.UTF8String, name);
    const char *reason = exception.reason.UTF8String;
    char digest[65];
    const char *digestPtr = NULL;
    if (reason != NULL) {
        JCSpikeSha256Hex(reason, strlen(reason), digest);
        digestPtr = digest;
    }
    JCSpikeWriteLiteral(STDERR_FILENO,
        "[contacts-app-spike] uncaught_objc_exception name=");
    JCSpikeWriteLiteral(STDERR_FILENO, name);
    JCSpikeWriteLiteral(STDERR_FILENO, " reasonDigest=");
    JCSpikeWriteLiteral(STDERR_FILENO, digestPtr ? digestPtr : "unavailable");
    JCSpikeWriteLiteral(STDERR_FILENO, "\n");
    if (gSpikeDiag.fd >= 0) {
        JCSpikeCommitDiag("app-spike-uncaught", name, reason, digestPtr);
    }
    if (gSpikePreviousHandler != NULL) { gSpikePreviousHandler(exception); }
}

static void JCSpikeInstallUncaught(void) {
    if (gSpikeUncaughtInstalled) { return; }
    gSpikeUncaughtInstalled = YES;
    gSpikePreviousHandler = NSGetUncaughtExceptionHandler();
    NSSetUncaughtExceptionHandler(&JCSpikeUncaughtHandler);
}

// ── Operationsobjekt: der eine Ablauf, zwei Anbindungen ─────────────────────

typedef NS_ENUM(int32_t, JCSpikeAuth) {
    JCSpikeAuthNotAuthorized = 0,
    JCSpikeAuthAuthorized = 1,
};

@interface JCSpikeOps : NSObject
/// CNAuthorizationStatus lesen (nie anfordern).
@property (nonatomic, copy) JCSpikeAuth (^authorization)(void);
/// Identifier aller Container der Art `local` — Auswahl ausschliesslich
/// nach TYP, nie nach Reihenfolge oder Kontaktzahl.
@property (nonatomic, copy) NSArray<NSString *> *(^localContainerIdentifiers)
    (NSError *__autoreleasing *error);
/// Echter minimaler Kontakt-Fetch als Diagnose (nicht existente Kennung).
@property (nonatomic, copy) BOOL (^probeFetch)(NSError *__autoreleasing *);
/// GENAU EIN Save des fest gebauten Kontakts in den Zielcontainer.
/// Liefert bei Erfolg den neuen Provider-Identifier.
@property (nonatomic, copy) NSString *_Nullable (^save)
    (NSString *containerIdentifier, NSError *__autoreleasing *error);
/// Read-back des konkret geschriebenen Kontakts: existiert er, stimmt der
/// Vorname? (Nur ein Bool verlässt den Shim — nie der Wert.)
@property (nonatomic, copy) BOOL (^readback)(NSString *providerIdentifier,
                                             BOOL *givenNameMatched);
@end

@implementation JCSpikeOps
@end

// ── Der eine Ablauf ─────────────────────────────────────────────────────────

static void JCSpikeRun(JCSpikeOps *ops, JCAppSaveSpikeResult *out) {
    memset(out, 0, sizeof(*out));
    JCSpikeInstallUncaught();

    // 1./2. Status lesen — nie anfordern.
    if (ops.authorization() != JCSpikeAuthAuthorized) {
        out->outcome = JCAppSaveSpikeOutcomeNotAuthorized;
        return;
    }

    // 3./4. Genau EIN Container der Art `local`.
    NSError *error = nil;
    NSArray<NSString *> *lokale = ops.localContainerIdentifiers(&error);
    if (lokale == nil || lokale.count == 0) {
        out->outcome = JCAppSaveSpikeOutcomeLocalContainerNotFound;
        if (error != nil) {
            JCSpikeSanitizeDomain(error.domain.UTF8String, out->error_domain);
            out->error_code = error.code;
        }
        return;
    }
    if (lokale.count > 1) {
        out->outcome = JCAppSaveSpikeOutcomeLocalContainerAmbiguous;
        return;
    }
    NSString *ziel = lokale.firstObject;

    // 5. Echter Kontakt-Fetch als Diagnose — scheitert er, gibt es keinen
    //    CNSaveRequest und keinen Save.
    error = nil;
    if (!ops.probeFetch(&error)) {
        out->outcome = JCAppSaveSpikeOutcomeReadPreflightFailed;
        if (error != nil) {
            JCSpikeSanitizeDomain(error.domain.UTF8String, out->error_domain);
            out->error_code = error.code;
        }
        return;
    }

    // 6.–10. Genau ein Save, in der @try/@catch-Grenze; Artefakt vorbereitet.
    JCSpikePrepareDiag();
    NSString *neueKennung = nil;
    @try {
        error = nil;
        neueKennung = ops.save(ziel, &error);
        out->save_attempts = 1;
        if (neueKennung == nil) {
            out->outcome = JCAppSaveSpikeOutcomeSaveError;
            if (error != nil) {
                JCSpikeSanitizeDomain(error.domain.UTF8String,
                                      out->error_domain);
                out->error_code = error.code;
            } else {
                strlcpy(out->error_domain, "JCContactsAppSaveSpike",
                        sizeof(out->error_domain));
                out->error_code = -1;
            }
            JCSpikeDiscardDiag();
            return;
        }
    }
    @catch (NSException *exception) {
        out->save_attempts = 1;
        out->outcome = JCAppSaveSpikeOutcomeCaughtException;
        JCSpikeSanitizeName(exception.name.UTF8String, out->exception_name);
        const char *reason = exception.reason.UTF8String;
        out->reason_present = (reason != NULL);
        const char *digestPtr = NULL;
        if (reason != NULL) {
            JCSpikeSha256Hex(reason, strlen(reason), out->reason_digest);
            digestPtr = out->reason_digest;
        }
        out->diagnostics_artifact_written = JCSpikeCommitDiag(
            "app-spike-catch", out->exception_name, reason, digestPtr);
        return;
    }
    JCSpikeDiscardDiag();

    // 11. Read-back des konkret geschriebenen Kontakts.
    out->outcome = JCAppSaveSpikeOutcomeApplied;
    out->provider_identifier_present = 1;
    JCSpikeSha256Hex(neueKennung.UTF8String, strlen(neueKennung.UTF8String),
                     out->provider_identifier_digest);
    BOOL matched = NO;
    out->readback_succeeded = ops.readback(neueKennung, &matched) ? 1 : 0;
    out->given_name_matched = matched ? 1 : 0;
    strlcpy(out->container_type, "local", sizeof(out->container_type));
}

// ── Produktivanbindung: echter CNContactStore ───────────────────────────────

static JCSpikeOps *JCSpikeRealOps(void) {
    // GENAU EIN produktiver CNContactStore im Spike-Kern; dieselbe Instanz
    // trägt Inventar, Diagnose-Fetch, Save und Read-back.
    CNContactStore *store = [[CNContactStore alloc] init];
    JCSpikeOps *ops = [[JCSpikeOps alloc] init];

    ops.authorization = ^JCSpikeAuth {
        return ([CNContactStore authorizationStatusForEntityType:
                    CNEntityTypeContacts] == CNAuthorizationStatusAuthorized)
            ? JCSpikeAuthAuthorized : JCSpikeAuthNotAuthorized;
    };

    ops.localContainerIdentifiers =
        ^NSArray<NSString *> *(NSError *__autoreleasing *error) {
        NSArray<CNContainer *> *alle =
            [store containersMatchingPredicate:nil error:error];
        if (alle == nil) { return nil; }
        NSMutableArray<NSString *> *lokale = [NSMutableArray array];
        for (CNContainer *c in alle) {
            if (c.type == CNContainerTypeLocal) {
                [lokale addObject:c.identifier];
            }
        }
        return lokale;
    };

    ops.probeFetch = ^BOOL(NSError *__autoreleasing *error) {
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:@[ CNContactIdentifierKey ]];
        req.unifyResults = NO;
        req.mutableObjects = NO;
        NSString *probe = [NSString stringWithFormat:@"JC-APP-SPIKE-%@",
                           NSUUID.UUID.UUIDString];
        req.predicate =
            [CNContact predicateForContactsWithIdentifiers:@[ probe ]];
        return [store enumerateContactsWithFetchRequest:req
                                                  error:error
                                             usingBlock:
            ^(CNContact *contact, BOOL *stop) { *stop = YES; }];
    };

    ops.save = ^NSString *_Nullable(NSString *containerIdentifier,
                                    NSError *__autoreleasing *error) {
        CNMutableContact *neu = [[CNMutableContact alloc] init];
        neu.contactType = CNContactTypePerson;
        neu.givenName = kSpikeGivenName;
        CNSaveRequest *req = [[CNSaveRequest alloc] init];
        if (@available(macOS 12.0, *)) {
            req.transactionAuthor = kSpikeTransactionAuthor;
        }
        [req addContact:neu toContainerWithIdentifier:containerIdentifier];
        BOOL ok = [store executeSaveRequest:req error:error];
        return ok ? neu.identifier : nil;
    };

    ops.readback = ^BOOL(NSString *providerIdentifier, BOOL *givenNameMatched) {
        CNContactFetchRequest *req = [[CNContactFetchRequest alloc]
            initWithKeysToFetch:@[ CNContactIdentifierKey,
                                   CNContactGivenNameKey ]];
        req.unifyResults = NO;
        req.mutableObjects = NO;
        req.predicate = [CNContact
            predicateForContactsWithIdentifiers:@[ providerIdentifier ]];
        __block BOOL gefunden = NO;
        __block BOOL matched = NO;
        NSError *fehler = nil;
        BOOL ok = [store enumerateContactsWithFetchRequest:req
                                                     error:&fehler
                                                usingBlock:
            ^(CNContact *contact, BOOL *stop) {
                gefunden = YES;
                matched = [contact.givenName isEqualToString:kSpikeGivenName];
                *stop = YES;
            }];
        *givenNameMatched = matched;
        return ok && gefunden;
    };

    return ops;
}

void jc_app_save_spike_run(JCAppSaveSpikeResult *out) {
    JCSpikeRun(JCSpikeRealOps(), out);
}

void jc_app_save_spike_payload_digest(char out[65]) {
    // Kanonische Form des festen Payloads — deterministisch, eine Wahrheit.
    NSString *kanonisch = [NSString stringWithFormat:
        @"contactType=person\ngivenName=%@\n", kSpikeGivenName];
    const char *utf8 = kanonisch.UTF8String;
    JCSpikeSha256Hex(utf8, strlen(utf8), out);
}

// ── Kontaktfreier Testeinstieg: Fakes, kein Store ───────────────────────────

void jc_app_save_spike_run_scenario(int32_t scenario,
                                    JCAppSaveSpikeResult *out) {
    JCSpikeOps *ops = [[JCSpikeOps alloc] init];
    __block int saveCalls = 0;

    ops.authorization = ^JCSpikeAuth {
        return scenario == JCSpikeScenarioNotAuthorized
            ? JCSpikeAuthNotAuthorized : JCSpikeAuthAuthorized;
    };
    ops.localContainerIdentifiers =
        ^NSArray<NSString *> *(NSError *__autoreleasing *error) {
        switch (scenario) {
            case JCSpikeScenarioNoLocalContainer: return @[];
            case JCSpikeScenarioTwoLocalContainers:
                return @[ @"fake-local-a", @"fake-local-b" ];
            default: return @[ @"fake-local" ];
        }
    };
    ops.probeFetch = ^BOOL(NSError *__autoreleasing *error) {
        if (scenario == JCSpikeScenarioFetchFails) {
            if (error) {
                *error = [NSError errorWithDomain:@"CNErrorDomain"
                                             code:102
                                         userInfo:nil];
            }
            return NO;
        }
        return YES;
    };
    ops.save = ^NSString *_Nullable(NSString *container,
                                    NSError *__autoreleasing *error) {
        saveCalls++;
        if (saveCalls > 1) {
            // Der Ablauf selbst darf nie zweimal speichern — sichtbar machen.
            @throw [NSException exceptionWithName:@"JCSpikeDoubleSave"
                                           reason:@"double save"
                                         userInfo:nil];
        }
        switch (scenario) {
            case JCSpikeScenarioSaveNSError:
                if (error) {
                    *error = [NSError errorWithDomain:@"NSCocoaErrorDomain"
                                                 code:513
                                             userInfo:nil];
                }
                return nil;
            case JCSpikeScenarioSaveThrows:
                @throw [[NSException alloc]
                    initWithName:@"NSInternalInconsistencyException"
                          reason:@"Fake-Reason 'ZZZ-Geheim' "
                                 @"<geheim@example.invalid> /Users/erfunden"
                        userInfo:nil];
            default:
                return @"FAKE-PROVIDER-IDENTIFIER-0000";
        }
    };
    ops.readback = ^BOOL(NSString *providerIdentifier, BOOL *matched) {
        if (scenario == JCSpikeScenarioReadbackMissing) {
            *matched = NO;
            return NO;
        }
        *matched = YES;
        return YES;
    };

    JCSpikeRun(ops, out);
}

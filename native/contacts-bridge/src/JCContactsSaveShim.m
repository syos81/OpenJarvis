//  JCContactsSaveShim.m — produktive Kontakte-Bridge.
//
//  Umsetzung der @try/@catch-Grenze aus JCContactsSaveShim.h. Die
//  Kommentare dort gelten wortgleich; hier steht nur das Wie.

#import "JCContactsSaveShim.h"

#import <CommonCrypto/CommonDigest.h>
#import <sys/stat.h>
#import <sys/utsname.h>
#import <fcntl.h>
#import <unistd.h>

NSString *const JCExceptionDiagnosticsPathEnvVar =
    @"OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH";

// ── Ergebnisobjekt ───────────────────────────────────────────────────────────

@interface JCSaveOutcome ()
@property (nonatomic, readwrite) JCSaveOutcomeKind kind;
@property (nonatomic, readwrite, nullable) NSError *error;
@property (nonatomic, readwrite, nullable) NSString *exceptionName;
@property (nonatomic, readwrite) BOOL reasonPresent;
@property (nonatomic, readwrite, nullable) NSString *reasonDigest;
@property (nonatomic, readwrite, nullable) NSString *sanitizedDiagnostic;
@property (nonatomic, readwrite) BOOL diagnosticsArtifactWritten;
@property (nonatomic, readwrite) BOOL processMustTerminate;
@end

@implementation JCSaveOutcome
@end

// ── Hilfen (modulprivat) ─────────────────────────────────────────────────────

/// SHA-256-Hexdigest des UTF-8-Texts. Nil bei nil.
static NSString *_Nullable JCSha256Hex(NSString *_Nullable text) {
    if (text == nil) { return nil; }
    NSData *data = [text dataUsingEncoding:NSUTF8StringEncoding];
    if (data == nil) { return nil; }
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, digest);
    NSMutableString *hex =
        [NSMutableString stringWithCapacity:CC_SHA256_DIGEST_LENGTH * 2];
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        [hex appendFormat:@"%02x", digest[i]];
    }
    return hex;
}

/// Klassenname → [A-Za-z0-9_], max. 64 Zeichen, nie leer. Ein
/// Ausnahmename ist ein Bezeichner; alles andere (Pfade, `@`, Leerzeichen)
/// hat darin nichts verloren und wird entfernt statt maskiert.
static NSString *JCSanitizedExceptionName(NSString *_Nullable name) {
    if (name.length == 0) { return @"UnknownException"; }
    NSMutableString *out = [NSMutableString stringWithCapacity:name.length];
    NSCharacterSet *allowed = [NSCharacterSet
        characterSetWithCharactersInString:
            @"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"];
    for (NSUInteger i = 0; i < name.length && out.length < 64; i++) {
        unichar c = [name characterAtIndex:i];
        if ([allowed characterIsMember:c]) {
            [out appendFormat:@"%C", c];
        }
    }
    return out.length ? out : @"UnknownException";
}

/// Ist der Diagnoseordner verwendbar? Regeln aus dem Auftrag §4:
/// absoluter Pfad, existiert, KEIN Symlink, gehoert dem effektiven Nutzer,
/// Modus exakt 0700. Alles andere: kein Artefakt — still.
static BOOL JCDiagnosticsDirUsable(NSString *dir) {
    if (dir.length == 0 || ![dir hasPrefix:@"/"]) { return NO; }
    const char *cdir = dir.fileSystemRepresentation;
    struct stat st;
    if (lstat(cdir, &st) != 0) { return NO; }
    if (S_ISLNK(st.st_mode) || !S_ISDIR(st.st_mode)) { return NO; }
    if (st.st_uid != geteuid()) { return NO; }
    if ((st.st_mode & 0777) != 0700) { return NO; }
    return YES;
}

/// Monotoner Zaehler, damit zwei Artefakte desselben Prozesses nie
/// denselben Namen tragen. `O_EXCL` bleibt trotzdem die harte Garantie.
static long JCNextArtifactSequence(void) {
    static long sequence = 0;
    return ++sequence;
}

/// Schreibt den Roh-Reason als exklusive 0600-JSON-Datei — ausschliesslich
/// wenn der Diagnosemodus ausdruecklich aktiviert und der Zielordner streng
/// geeignet ist. Ein Fehler hier ist folgenlos fuer die Klassifikation.
///
/// Inhalt bewusst begrenzt (Auftrag §4): Zeitstempel, Ausnahmename, Reason,
/// Digest, Vertrags-/Sidecarversionen, Architektur, OS-Version. KEINE
/// Kontaktnutzlast, KEINE Anfrage, KEINE Provider- oder Containerkennung.
static BOOL JCWriteDiagnosticsArtifact(NSString *sanitizedName,
                                       NSString *_Nullable reason,
                                       NSString *_Nullable reasonDigest,
                                       int mutationContractVersion,
                                       int fieldContractVersion) {
    NSDictionary *env = NSProcessInfo.processInfo.environment;
    NSString *dir = env[JCExceptionDiagnosticsPathEnvVar];
    if (dir == nil) { return NO; }                  // Standard: kein Artefakt.
    if (!JCDiagnosticsDirUsable(dir)) { return NO; }

    struct utsname uts;
    NSString *arch = @"unknown";
    if (uname(&uts) == 0) {
        arch = [NSString stringWithUTF8String:uts.machine] ?: @"unknown";
    }
    NSOperatingSystemVersion os =
        NSProcessInfo.processInfo.operatingSystemVersion;

    NSMutableDictionary *doc = [NSMutableDictionary dictionary];
    doc[@"capturedAt"] = @([NSDate date].timeIntervalSince1970);
    doc[@"exceptionName"] = sanitizedName;
    doc[@"reasonPresent"] = @(reason != nil);
    if (reason != nil) { doc[@"reason"] = reason; }
    if (reasonDigest != nil) { doc[@"reasonDigest"] = reasonDigest; }
    doc[@"mutationContractVersion"] = @(mutationContractVersion);
    doc[@"fieldContractVersion"] = @(fieldContractVersion);
    doc[@"architecture"] = arch;
    doc[@"osVersion"] = [NSString stringWithFormat:@"%ld.%ld.%ld",
                         (long)os.majorVersion, (long)os.minorVersion,
                         (long)os.patchVersion];

    NSData *json = [NSJSONSerialization dataWithJSONObject:doc
                                                   options:NSJSONWritingSortedKeys
                                                     error:NULL];
    if (json == nil) { return NO; }

    NSString *name = [NSString stringWithFormat:
        @"contacts-exception-%.0f-%d-%ld.json",
        [NSDate date].timeIntervalSince1970 * 1000.0, getpid(),
        JCNextArtifactSequence()];
    NSString *path = [dir stringByAppendingPathComponent:name];

    // O_EXCL: niemals eine bestehende Datei ueberschreiben. O_NOFOLLOW:
    // auch die Zieldatei darf kein Symlink sein. 0600: nur der Nutzer.
    int fd = open(path.fileSystemRepresentation,
                  O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) { return NO; }
    BOOL written = NO;
    ssize_t rc = write(fd, json.bytes, json.length);
    if (rc == (ssize_t)json.length) {
        written = (fsync(fd) == 0);
    }
    close(fd);
    return written;
}

// Die Vertragsversionen des Sidecars. Wortgleich zu sidecar.swift; ein
// Auseinanderlaufen faellt im Protokolltest auf (Handshake nennt beide).
static const int kJCMutationContractVersion = 1;
static const int kJCFieldContractVersion = 1;

// ── Kern: die @try/@catch-Grenze ─────────────────────────────────────────────

JCSaveOutcome *JCExecuteSaveGuardedWithAttempt(
    BOOL (NS_NOESCAPE ^attempt)(NSError *_Nullable *_Nullable error)) {
    JCSaveOutcome *outcome = [[JCSaveOutcome alloc] init];
    NSError *error = nil;
    @try {
        BOOL success = attempt(&error);
        if (success) {
            outcome.kind = JCSaveOutcomeKindSuccess;
        } else {
            outcome.kind = JCSaveOutcomeKindError;
            // Ein NO ohne NSError waere ein Vertragsbruch des Frameworks;
            // er wird sichtbar gemacht statt als Erfolg durchgewunken.
            outcome.error = error
                ?: [NSError errorWithDomain:@"JCContactsSaveShim"
                                       code:-1
                                   userInfo:nil];
        }
        outcome.processMustTerminate = NO;
    }
    @catch (NSException *exception) {
        // Ab hier ist der Store-Zustand undefiniert. Es gibt keinen zweiten
        // Versuch, kein Lesen, keine Weiterverwendung — nur Befund und Ende.
        NSString *sanitizedName = JCSanitizedExceptionName(exception.name);
        NSString *reason = exception.reason;
        NSString *digest = JCSha256Hex(reason);

        outcome.kind = JCSaveOutcomeKindException;
        outcome.exceptionName = sanitizedName;
        outcome.reasonPresent = (reason != nil);
        outcome.reasonDigest = digest;
        outcome.processMustTerminate = YES;
        outcome.diagnosticsArtifactWritten = JCWriteDiagnosticsArtifact(
            sanitizedName, reason, digest,
            kJCMutationContractVersion, kJCFieldContractVersion);
        // Der Einzeiler fuer stderr: Klassenname, Praesenz, Digest-Praefix.
        // Bewusst KEIN Fragment des Reason-Texts — der existiert ausserhalb
        // des Artefakts nur als Digest.
        outcome.sanitizedDiagnostic = [NSString stringWithFormat:
            @"NSException name=%@ reasonPresent=%d reasonDigest=%@ artifact=%d",
            sanitizedName, outcome.reasonPresent,
            digest ? [digest substringToIndex:16] : @"none",
            outcome.diagnosticsArtifactWritten];
    }
    return outcome;
}

JCSaveOutcome *JCExecuteSaveRequestGuarded(CNContactStore *store,
                                           CNSaveRequest *request) {
    // GENAU EIN Aufruf. Kein Retry, keine Schleife, kein zweiter Request.
    return JCExecuteSaveGuardedWithAttempt(
        ^BOOL(NSError *_Nullable *_Nullable error) {
            return [store executeSaveRequest:request error:error];
        });
}

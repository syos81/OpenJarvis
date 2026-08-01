//  JCContactsSaveShim.m — produktive Kontakte-Bridge.
//
//  Umsetzung der @try/@catch-Grenze UND der Uncaught-Letztdiagnose aus
//  JCContactsSaveShim.h. Die Kommentare dort gelten wortgleich; hier steht
//  nur das Wie.
//
//  Aufbau in drei Schichten:
//
//  1. Vorbereiteter Diagnosekontext (VOR dem Save): Ordner validieren,
//     Artefaktdatei exklusiv 0600 anlegen, Deskriptor und vorab berechnete
//     Metadaten global hinterlegen. Im Todesmoment ist damit kein open(),
//     keine Pfadaufloesung und keine Ordnerpruefung mehr noetig.
//  2. @try/@catch um GENAU EINEN executeSaveRequest-Aufruf — faengt, was
//     fangbar ist (Wuerfe ausserhalb der Dispatch-Grenze).
//  3. NSSetUncaughtExceptionHandler — sieht als Einziger die Wuerfe aus
//     Apples performBlockAndWait-Pfad, unmittelbar vor der unvermeidbaren
//     Terminierung. Best-effort, C-nah, ohne dynamische Strukturen.

#import "JCContactsSaveShim.h"

#import <CommonCrypto/CommonDigest.h>
#import <sys/stat.h>
#import <sys/utsname.h>
#import <fcntl.h>
#import <unistd.h>
#import <string.h>

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

// ── Vertragskonstanten (wortgleich zu sidecar.swift; Protokolltest prueft) ──
static const int kJCMutationContractVersion = 1;
static const int kJCFieldContractVersion = 1;

//: Laengsgrenze des Reason-Texts IM ARTEFAKT. Der Digest entsteht immer
//: ueber den unveraenderten vollen Text (ADR-0019 §4a); die Datei kappt nur
//: die Rohfassung, damit ein pathologisch langer Reason den Todesmoment
//: nicht dehnt.
#define JC_REASON_MAX_BYTES 4096

// ── Globaler Diagnosekontext ─────────────────────────────────────────────────
//
// Klein und bewusst C-nah: Der Uncaught-Handler laeuft im Terminierungspfad
// und soll ausschliesslich write(2) auf einen BEREITS offenen Deskriptor
// brauchen. Alles Wissen (Pfad, Architektur, OS, Laufkennung) entsteht beim
// Vorbereiten — nie im Handler.
static struct {
    int  fd;                 // -1 = kein vorbereitetes Artefakt
    long sequence;           // eindeutige Zuordnung: genau EIN Save-Versuch
    char path[1024];         // fuer unlink beim Verwerfen
    char arch[32];
    char os[32];
    double preparedAt;       // Epochensekunden beim Vorbereiten
} gDiag = { .fd = -1 };

static NSUncaughtExceptionHandler *gPreviousUncaughtHandler = NULL;
static BOOL gUncaughtInstalled = NO;

// ── Hilfen (modulprivat) ─────────────────────────────────────────────────────

/// SHA-256-Hexdigest eines C-Puffers in `out` (mind. 65 Bytes). Reine
/// C-Routine — im Terminierungspfad verwendbar.
static void JCSha256HexRaw(const char *bytes, size_t len, char out[65]) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(bytes, (CC_LONG)len, digest);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < CC_SHA256_DIGEST_LENGTH; i++) {
        out[i * 2]     = hex[digest[i] >> 4];
        out[i * 2 + 1] = hex[digest[i] & 0x0F];
    }
    out[64] = '\0';
}

/// SHA-256-Hexdigest des UTF-8-Texts. Nil bei nil.
static NSString *_Nullable JCSha256Hex(NSString *_Nullable text) {
    if (text == nil) { return nil; }
    const char *utf8 = text.UTF8String;
    if (utf8 == NULL) { return nil; }
    char out[65];
    JCSha256HexRaw(utf8, strlen(utf8), out);
    return [NSString stringWithUTF8String:out];
}

/// Klassenname → [A-Za-z0-9_] in einen statischen Puffer, max. 64 Zeichen,
/// nie leer. C-nah, damit auch der Uncaught-Handler sie nutzen kann.
static void JCSanitizeExceptionNameRaw(const char *_Nullable name,
                                       char out[65]) {
    size_t n = 0;
    for (const char *p = name; p != NULL && *p != '\0' && n < 64; p++) {
        char c = *p;
        if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
            || (c >= '0' && c <= '9') || c == '_') {
            out[n++] = c;
        }
    }
    if (n == 0) {
        strlcpy(out, "UnknownException", 65);
    } else {
        out[n] = '\0';
    }
}

static NSString *JCSanitizedExceptionName(NSString *_Nullable name) {
    char out[65];
    JCSanitizeExceptionNameRaw(name.UTF8String, out);
    return [NSString stringWithUTF8String:out];
}

/// Ist der Diagnoseordner verwendbar? Regeln unveraendert (Auftrag §4 vom
/// 2026-08-01): absoluter Pfad, existiert, KEIN Symlink, gehoert dem
/// effektiven Nutzer, Modus exakt 0700. Alles andere: kein Artefakt — still.
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

/// Monotoner Zaehler — zwei Artefakte desselben Prozesses tragen nie
/// denselben Namen. `O_EXCL` bleibt trotzdem die harte Garantie.
static long JCNextArtifactSequence(void) {
    static long sequence = 0;
    return ++sequence;
}

// ── JSON-Schreiben ohne dynamische Strukturen ────────────────────────────────

/// Schreibt `s` JSON-escaped (", \, Steuerzeichen) auf `fd`, hoechstens
/// `maxBytes` Quellbytes. Reines write(2) — terminierungsfest.
static void JCWriteJsonEscaped(int fd, const char *_Nullable s,
                               size_t maxBytes) {
    if (s == NULL) { return; }
    char puffer[512];
    size_t p = 0;
    for (size_t i = 0; s[i] != '\0' && i < maxBytes; i++) {
        unsigned char c = (unsigned char)s[i];
        if (p > sizeof(puffer) - 8) {
            write(fd, puffer, p);
            p = 0;
        }
        if (c == '"' || c == '\\') {
            puffer[p++] = '\\';
            puffer[p++] = (char)c;
        } else if (c < 0x20) {
            p += (size_t)snprintf(puffer + p, 8, "\\u%04x", c);
        } else {
            puffer[p++] = (char)c;
        }
    }
    if (p > 0) { write(fd, puffer, p); }
}

static void JCWriteLiteral(int fd, const char *s) {
    write(fd, s, strlen(s));
}

/// Schreibt das vollstaendige Artefakt-JSON auf den offenen Deskriptor.
/// `source` unterscheidet "catch" (fangbarer Wurf) von "uncaught"
/// (Dispatch-Wurf im Terminierungspfad).
static void JCWriteArtifactJson(int fd, const char *source,
                                const char sanitizedName[65],
                                const char *_Nullable reasonUtf8,
                                const char *_Nullable digestHex) {
    char zahl[64];
    JCWriteLiteral(fd, "{\"source\":\"");
    JCWriteLiteral(fd, source);
    JCWriteLiteral(fd, "\",\"preparedAt\":");
    snprintf(zahl, sizeof(zahl), "%.3f", gDiag.preparedAt);
    JCWriteLiteral(fd, zahl);
    JCWriteLiteral(fd, ",\"sequence\":");
    snprintf(zahl, sizeof(zahl), "%ld", gDiag.sequence);
    JCWriteLiteral(fd, zahl);
    JCWriteLiteral(fd, ",\"exceptionName\":\"");
    JCWriteJsonEscaped(fd, sanitizedName, 64);
    JCWriteLiteral(fd, "\",\"reasonPresent\":");
    JCWriteLiteral(fd, reasonUtf8 ? "true" : "false");
    if (reasonUtf8 != NULL) {
        size_t voll = strlen(reasonUtf8);
        JCWriteLiteral(fd, ",\"reasonTruncated\":");
        JCWriteLiteral(fd, voll > JC_REASON_MAX_BYTES ? "true" : "false");
        JCWriteLiteral(fd, ",\"reason\":\"");
        JCWriteJsonEscaped(fd, reasonUtf8, JC_REASON_MAX_BYTES);
        JCWriteLiteral(fd, "\"");
    }
    if (digestHex != NULL) {
        JCWriteLiteral(fd, ",\"reasonDigest\":\"");
        JCWriteLiteral(fd, digestHex);
        JCWriteLiteral(fd, "\"");
    }
    JCWriteLiteral(fd, ",\"mutationContractVersion\":");
    snprintf(zahl, sizeof(zahl), "%d", kJCMutationContractVersion);
    JCWriteLiteral(fd, zahl);
    JCWriteLiteral(fd, ",\"fieldContractVersion\":");
    snprintf(zahl, sizeof(zahl), "%d", kJCFieldContractVersion);
    JCWriteLiteral(fd, zahl);
    JCWriteLiteral(fd, ",\"architecture\":\"");
    JCWriteJsonEscaped(fd, gDiag.arch, sizeof(gDiag.arch));
    JCWriteLiteral(fd, "\",\"osVersion\":\"");
    JCWriteJsonEscaped(fd, gDiag.os, sizeof(gDiag.os));
    JCWriteLiteral(fd, "\"}");
}

// ── Vorbereiteter Diagnosekontext ────────────────────────────────────────────

/// Verwirft ein vorbereitetes, ungenutztes Artefakt: Deskriptor schliessen,
/// leere Datei entfernen, Kontext loeschen. Nach Erfolg und nach NSError —
/// ein leeres Artefakt waere die falsche Aussage „hier starb etwas".
static void JCDiscardPreparedDiagnostics(void) {
    if (gDiag.fd < 0) { return; }
    close(gDiag.fd);
    unlink(gDiag.path);
    gDiag.fd = -1;
    gDiag.path[0] = '\0';
}

/// Bereitet das Diagnoseartefakt VOR dem Save vor — ausschliesslich wenn der
/// Diagnosemodus ausdruecklich aktiviert und der Zielordner streng geeignet
/// ist. Fehler sind still und folgenlos fuer die Klassifikation.
static void JCPrepareDiagnosticsForAttempt(void) {
    // Eindeutige Zuordnung: ein Kontext gehoert zu genau einem Versuch.
    JCDiscardPreparedDiagnostics();

    NSDictionary *env = NSProcessInfo.processInfo.environment;
    NSString *dir = env[JCExceptionDiagnosticsPathEnvVar];
    if (dir == nil) { return; }                    // Standard: kein Artefakt.
    if (!JCDiagnosticsDirUsable(dir)) { return; }

    // Metadaten JETZT erheben — der Handler liest sie nur noch.
    struct utsname uts;
    if (uname(&uts) == 0) {
        strlcpy(gDiag.arch, uts.machine, sizeof(gDiag.arch));
    } else {
        strlcpy(gDiag.arch, "unknown", sizeof(gDiag.arch));
    }
    NSOperatingSystemVersion os =
        NSProcessInfo.processInfo.operatingSystemVersion;
    snprintf(gDiag.os, sizeof(gDiag.os), "%ld.%ld.%ld",
             (long)os.majorVersion, (long)os.minorVersion,
             (long)os.patchVersion);
    gDiag.preparedAt = [NSDate date].timeIntervalSince1970;
    gDiag.sequence = JCNextArtifactSequence();

    NSString *name = [NSString stringWithFormat:
        @"contacts-exception-%.0f-%d-%ld.json",
        gDiag.preparedAt * 1000.0, getpid(), gDiag.sequence];
    NSString *path = [dir stringByAppendingPathComponent:name];
    if (strlcpy(gDiag.path, path.fileSystemRepresentation,
                sizeof(gDiag.path)) >= sizeof(gDiag.path)) {
        gDiag.path[0] = '\0';
        return;                                    // Pfad zu lang: kein Artefakt.
    }

    // O_EXCL: niemals eine bestehende Datei ueberschreiben. O_NOFOLLOW:
    // auch die Zieldatei darf kein Symlink sein. 0600: nur der Nutzer.
    int fd = open(gDiag.path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) {
        gDiag.path[0] = '\0';
        return;
    }
    gDiag.fd = fd;
}

/// Fuellt das vorbereitete Artefakt aus dem @catch-Pfad (regulaerer,
/// fangbarer Wurf) und schliesst es. Liefert, ob geschrieben wurde.
static BOOL JCCommitPreparedDiagnostics(const char *source,
                                        const char sanitizedName[65],
                                        NSString *_Nullable reason,
                                        NSString *_Nullable digest) {
    if (gDiag.fd < 0) { return NO; }
    JCWriteArtifactJson(gDiag.fd, source, sanitizedName,
                        reason.UTF8String, digest.UTF8String);
    BOOL ok = (fsync(gDiag.fd) == 0);
    close(gDiag.fd);
    gDiag.fd = -1;
    gDiag.path[0] = '\0';
    return ok;
}

// ── Uncaught-Handler: Letztdiagnose im Terminierungspfad ─────────────────────

static void JCUncaughtExceptionDiagnosticsHandler(NSException *exception) {
    // Best-effort, C-nah, keine Ordnererstellung, keine Pfadaufloesung,
    // keine Datenbank, keine dynamischen Strukturen. Reihenfolge: erst die
    // stderr-Zeile (immer), dann das Artefakt (falls vorbereitet), dann der
    // fremde Handler, dann Rueckkehr in die normale Terminierung.
    char name[65];
    JCSanitizeExceptionNameRaw(exception.name.UTF8String, name);

    const char *reasonUtf8 = exception.reason.UTF8String;
    char digest[65];
    const char *digestPtr = NULL;
    if (reasonUtf8 != NULL) {
        JCSha256HexRaw(reasonUtf8, strlen(reasonUtf8), digest);
        digestPtr = digest;
    }

    // PII-arm: Klassenname und Digest — nie der Reason selbst.
    JCWriteLiteral(STDERR_FILENO, "[contacts-bridge] uncaught_objc_exception name=");
    JCWriteLiteral(STDERR_FILENO, name);
    JCWriteLiteral(STDERR_FILENO, " reasonDigest=");
    JCWriteLiteral(STDERR_FILENO, digestPtr ? digestPtr : "unavailable");
    JCWriteLiteral(STDERR_FILENO, "\n");

    if (gDiag.fd >= 0) {
        JCWriteArtifactJson(gDiag.fd, "uncaught", name, reasonUtf8, digestPtr);
        // Bewusst ohne fsync-Garantie (Terminierungspfad); close best-effort.
        close(gDiag.fd);
        gDiag.fd = -1;
    }

    if (gPreviousUncaughtHandler != NULL) {
        gPreviousUncaughtHandler(exception);
    }
    // Rueckkehr: _objc_terminate setzt die Terminierung fort (SIGABRT).
}

void JCInstallUncaughtExceptionDiagnostics(void) {
    if (gUncaughtInstalled) { return; }
    gUncaughtInstalled = YES;
    // Ein fremder Handler wird gesichert und weiterhin aufgerufen — nie
    // unbemerkt ersetzt.
    gPreviousUncaughtHandler = NSGetUncaughtExceptionHandler();
    NSSetUncaughtExceptionHandler(&JCUncaughtExceptionDiagnosticsHandler);
}

// ── Kern: die @try/@catch-Grenze ─────────────────────────────────────────────

JCSaveOutcome *JCExecuteSaveGuardedWithAttempt(
    BOOL (NS_NOESCAPE ^attempt)(NSError *_Nullable *_Nullable error)) {
    JCSaveOutcome *outcome = [[JCSaveOutcome alloc] init];
    // Artefakt VOR dem Versuch vorbereiten: im Todesmoment bleibt nur write(2).
    JCPrepareDiagnosticsForAttempt();
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
        // Kein Wurf: das leere Artefakt verschwindet wieder.
        JCDiscardPreparedDiagnostics();
    }
    @catch (NSException *exception) {
        // Ab hier ist der Store-Zustand undefiniert. Es gibt keinen zweiten
        // Versuch, kein Lesen, keine Weiterverwendung — nur Befund und Ende.
        NSString *sanitizedName = JCSanitizedExceptionName(exception.name);
        NSString *reason = exception.reason;
        NSString *digest = JCSha256Hex(reason);
        char nameRaw[65];
        JCSanitizeExceptionNameRaw(exception.name.UTF8String, nameRaw);

        outcome.kind = JCSaveOutcomeKindException;
        outcome.exceptionName = sanitizedName;
        outcome.reasonPresent = (reason != nil);
        outcome.reasonDigest = digest;
        outcome.processMustTerminate = YES;
        outcome.diagnosticsArtifactWritten = JCCommitPreparedDiagnostics(
            "catch", nameRaw, reason, digest);
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

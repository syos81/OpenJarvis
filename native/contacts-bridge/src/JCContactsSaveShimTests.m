//  JCContactsSaveShimTests.m — kontaktfreier Harness der Save-Shim-Grenze.
//
//  Eigenstaendiges Testbinary (eigenes main), das AUSSCHLIESSLICH die
//  Block-Variante `JCExecuteSaveGuardedWithAttempt` mit Fakes aufruft:
//  Erfolg, NSError, @throw. Es beruehrt niemals einen CNContactStore und
//  fuehrt keinen Schreibzugriff auf Apple Contacts aus — die einzigen
//  Dateizugriffe gehen in ein selbst angelegtes mkdtemp-Verzeichnis.
//
//  Exit 0 = alle Pruefungen bestanden; sonst 1 mit Befund auf stderr.
//  build.sh baut und STARTET dieses Binary bei jedem Sidecar-Build; ein
//  gebrochener Shim kann damit gar nicht erst gepackt werden.

#import "JCContactsSaveShim.h"

#import <sys/stat.h>
#import <unistd.h>

static int gefehlt = 0;

static void pruefe(BOOL bedingung, NSString *name) {
    if (!bedingung) {
        gefehlt++;
        fprintf(stderr, "FEHLGESCHLAGEN: %s\n", name.UTF8String);
    }
}

/// Kontaktwert-Attrappen fuer den Datenschutztest H. Erfunden, `.invalid`.
static NSString *const kBoeserReason =
    @"Kontakt 'ZZZ-Geheimname Mustermensch' <zzz-geheim@example.invalid> "
    @"+49 30 999999 in Container 01234567-89AB-CDEF-0123-456789ABCDEF:ABAccount "
    @"unter /Users/erfunden/Library/AddressBook konnte nicht gesichert werden";

/// SHA-256("abc") — bekannter Vektor, prueft die Digestbildung selbst.
static NSString *const kAbcDigest =
    @"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

static NSArray<NSString *> *artefakte(NSString *dir) {
    return [[NSFileManager.defaultManager contentsOfDirectoryAtPath:dir
                                                              error:NULL]
        sortedArrayUsingSelector:@selector(compare:)];
}

int main(void) {
    @autoreleasepool {
        // ── A · Erfolg ──────────────────────────────────────────────────────
        __block int aufrufe = 0;
        JCSaveOutcome *erfolg = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) { aufrufe++; return YES; });
        pruefe(aufrufe == 1, @"A: genau ein Versuch");
        pruefe(erfolg.kind == JCSaveOutcomeKindSuccess, @"A: Ergebnis success");
        pruefe(erfolg.error == nil, @"A: kein NSError");
        pruefe(erfolg.exceptionName == nil, @"A: kein Ausnahmename");
        pruefe(!erfolg.processMustTerminate, @"A: Prozess darf weiterleben");
        pruefe(!erfolg.diagnosticsArtifactWritten, @"A: kein Artefakt");

        // ── B · NSError ─────────────────────────────────────────────────────
        aufrufe = 0;
        JCSaveOutcome *fehler = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) {
                aufrufe++;
                if (error) {
                    *error = [NSError errorWithDomain:@"CNErrorDomain"
                                                 code:2
                                             userInfo:nil];
                }
                return NO;
            });
        pruefe(aufrufe == 1, @"B: genau ein Versuch");
        pruefe(fehler.kind == JCSaveOutcomeKindError, @"B: Ergebnis error");
        pruefe([fehler.error.domain isEqualToString:@"CNErrorDomain"]
               && fehler.error.code == 2, @"B: NSError technisch erhalten");
        pruefe(!fehler.processMustTerminate, @"B: kein Terminierungszwang");

        // NO ohne gesetzten NSError: Vertragsbruch wird sichtbar, nie Erfolg.
        JCSaveOutcome *stumm = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) { return NO; });
        pruefe(stumm.kind == JCSaveOutcomeKindError && stumm.error != nil,
               @"B: NO ohne NSError bleibt ein Fehler mit Platzhalter");

        // ── C · NSException, Diagnosemodus AUS ──────────────────────────────
        unsetenv(JCExceptionDiagnosticsPathEnvVar.UTF8String);
        aufrufe = 0;
        JCSaveOutcome *ausnahme = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) {
                aufrufe++;
                [NSException raise:@"NSInternalInconsistencyException"
                            format:@"abc"];
                return YES;
            });
        pruefe(aufrufe == 1, @"C: hoechstens ein Versuch");
        pruefe(ausnahme.kind == JCSaveOutcomeKindException, @"C: Ergebnis exception");
        pruefe([ausnahme.exceptionName
                   isEqualToString:@"NSInternalInconsistencyException"],
               @"C: Ausnahmename erhalten");
        pruefe(ausnahme.reasonPresent, @"C: reasonPresent true");
        pruefe([ausnahme.reasonDigest isEqualToString:kAbcDigest],
               @"C: Digest ist SHA-256 des unveraenderten Reasons");
        pruefe(ausnahme.processMustTerminate, @"C: Terminierungszwang");
        pruefe(!ausnahme.diagnosticsArtifactWritten,
               @"C: ohne Umgebungsvariable kein Artefakt");
        pruefe([ausnahme.sanitizedDiagnostic containsString:@"reasonDigest=ba7816bf"]
               && ![ausnahme.sanitizedDiagnostic containsString:@"abc"],
               @"C: Diagnosetext traegt Digestpraefix, nie den Reason");

        // Name mit Pfad-, @- und Leerzeichen wird bereinigt, nicht maskiert.
        JCSaveOutcome *schmutzig = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) {
                [NSException raise:@"Evil/Name @x mit Pfad" format:@"r"];
                return YES;
            });
        pruefe([schmutzig.exceptionName isEqualToString:@"EvilNamexmitPfad"],
               @"C: Ausnahmename wird auf Bezeichnerzeichen reduziert");

        // Reason kann fehlen: NSException ohne reason.
        JCSaveOutcome *ohneReason = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) {
                @throw [[NSException alloc] initWithName:@"X"
                                                  reason:nil
                                                userInfo:nil];
                return YES;
            });
        pruefe(!ohneReason.reasonPresent && ohneReason.reasonDigest == nil,
               @"C: fehlender Reason wird als abwesend gemeldet");

        // ── E · Diagnosemodus AN (Ordner 0700) ──────────────────────────────
        char schablone[] = "/tmp/jc-shim-tests-XXXXXX";
        NSString *dir = [NSString stringWithUTF8String:mkdtemp(schablone)];
        chmod(dir.fileSystemRepresentation, 0700);
        setenv(JCExceptionDiagnosticsPathEnvVar.UTF8String,
               dir.fileSystemRepresentation, 1);

        JCSaveOutcome *mitArtefakt = JCExecuteSaveGuardedWithAttempt(
            ^BOOL(NSError **error) {
                [NSException raise:@"NSGenericException"
                            format:@"%@", kBoeserReason];
                return YES;
            });
        pruefe(mitArtefakt.diagnosticsArtifactWritten, @"E: Artefakt geschrieben");
        NSArray<NSString *> *dateien = artefakte(dir);
        pruefe(dateien.count == 1, @"E: genau eine Datei");
        NSString *pfad = [dir stringByAppendingPathComponent:dateien.firstObject];
        struct stat st;
        pruefe(lstat(pfad.fileSystemRepresentation, &st) == 0
               && (st.st_mode & 0777) == 0600, @"E: Datei hat Modus 0600");
        NSData *inhaltDaten = [NSData dataWithContentsOfFile:pfad];
        NSDictionary *inhalt = [NSJSONSerialization JSONObjectWithData:inhaltDaten
                                                               options:0
                                                                 error:NULL];
        pruefe([inhalt[@"reason"] isEqualToString:kBoeserReason],
               @"E: Roh-Reason exakt im geschuetzten Artefakt");
        pruefe([inhalt[@"reasonDigest"] isEqualToString:mitArtefakt.reasonDigest],
               @"E: Digest im Artefakt stimmt mit Ergebnis ueberein");
        pruefe(inhalt[@"fields"] == nil && inhalt[@"containerIdentifier"] == nil
               && inhalt[@"mutationId"] == nil,
               @"E: keine Kontaktnutzlast und keine Kennungen im Artefakt");

        // Zweiter Wurf: zweite Datei, keine Ueberschreibung der ersten.
        JCExecuteSaveGuardedWithAttempt(^BOOL(NSError **error) {
            [NSException raise:@"NSGenericException" format:@"zweiter"];
            return YES;
        });
        pruefe(artefakte(dir).count == 2, @"E: zweiter Wurf ergibt zweite Datei");
        pruefe([[NSData dataWithContentsOfFile:pfad] isEqualToData:inhaltDaten],
               @"E: erste Datei blieb byte-identisch");

        // ── H · Datenschutz: boeser Reason erscheint nirgends normal ────────
        pruefe(![mitArtefakt.sanitizedDiagnostic containsString:@"ZZZ-Geheimname"]
               && ![mitArtefakt.sanitizedDiagnostic containsString:@"@"]
               && ![mitArtefakt.sanitizedDiagnostic containsString:@"999999"]
               && ![mitArtefakt.sanitizedDiagnostic containsString:@"/Users/"]
               && ![mitArtefakt.sanitizedDiagnostic containsString:@"ABAccount"],
               @"H: Diagnosetext ohne Namen, E-Mail, Nummer, Pfad, Kennung");
        pruefe(mitArtefakt.reasonDigest.length == 64
               && [mitArtefakt.reasonDigest
                      rangeOfCharacterFromSet:
                          [[NSCharacterSet
                              characterSetWithCharactersInString:
                                  @"0123456789abcdef"] invertedSet]]
                      .location == NSNotFound,
               @"H: Digest ist reiner Hex und traegt keinen Text");

        // ── F · Unsichere Diagnosepfade: still kein Artefakt ────────────────
        struct { const char *name; const char *wert; } faelle[3];
        faelle[0].name = "relativer Pfad";      faelle[0].wert = "relativ/ordner";
        NSString *offen = [dir stringByAppendingPathComponent:@"offen"];
        mkdir(offen.fileSystemRepresentation, 0755);
        faelle[1].name = "Ordner nicht 0700";   faelle[1].wert =
            offen.fileSystemRepresentation;
        NSString *link = [dir stringByAppendingPathComponent:@"link"];
        symlink(dir.fileSystemRepresentation, link.fileSystemRepresentation);
        faelle[2].name = "Symlink";             faelle[2].wert =
            link.fileSystemRepresentation;

        for (int i = 0; i < 3; i++) {
            setenv(JCExceptionDiagnosticsPathEnvVar.UTF8String,
                   faelle[i].wert, 1);
            JCSaveOutcome *o = JCExecuteSaveGuardedWithAttempt(
                ^BOOL(NSError **error) {
                    [NSException raise:@"X" format:@"%@", kBoeserReason];
                    return YES;
                });
            pruefe(o.kind == JCSaveOutcomeKindException && !o.diagnosticsArtifactWritten,
                   [NSString stringWithFormat:
                       @"F: %s wird abgewiesen, Klassifikation unveraendert",
                       faelle[i].name]);
        }
        pruefe(artefakte(offen).count == 0, @"F: offener Ordner blieb leer");
        unsetenv(JCExceptionDiagnosticsPathEnvVar.UTF8String);

        if (gefehlt == 0) {
            fprintf(stdout, "shim-tests: alle Pruefungen bestanden\n");
            return 0;
        }
        fprintf(stderr, "shim-tests: %d Pruefung(en) fehlgeschlagen\n", gefehlt);
        return 1;
    }
}

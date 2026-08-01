//  JCContactsSaveShim.h — produktive Kontakte-Bridge.
//
//  Zweck: eine Objective-C-@try/@catch-Grenze um GENAU EINEN Aufruf von
//  -[CNContactStore executeSaveRequest:error:]. Swift kann NSException nicht
//  fangen; ohne diese Grenze stirbt der Prozess per std::terminate/SIGABRT
//  und Klasse wie Begruendung der Ausnahme gehen verloren (belegt in beiden
//  x86_64-Create-Livetests am 2026-08-01).
//
//  Der Shim ist eine DIAGNOSE- UND PROZESSSICHERHEITSGRENZE, keine
//  Fehlerbehebung des Apple-Schreibpfads. Nach einer gefangenen NSException
//  ist der Zustand des Contacts-Stores undefiniert; der Vorgang gilt
//  zwingend als `outcome_unknown` (moeglicherweise angewandt — niemals
//  `not_sent`), und der Aufrufer muss den Prozess kontrolliert beenden.
//
//  VERBOTEN in dieser Datei (ADR-0016 Punkt 4, Auftrag 2026-08-01 §3):
//  kein Retry, kein zweiter CNSaveRequest, kein Lesen oder Suchen von
//  Kontakten, keine Domaenenentscheidung, keine Freigabepruefung, kein
//  Datenbankzugriff, keine Weiterverwendung des Store-Zustands nach der
//  Ausnahme. Der volle `reason` verlaesst dieses Modul nur als SHA-256-Digest
//  oder in das ausdruecklich aktivierte, exklusiv erzeugte Diagnoseartefakt.

#import <Foundation/Foundation.h>
#import <Contacts/Contacts.h>

NS_ASSUME_NONNULL_BEGIN

/// Die drei — und nur drei — Ausgaenge des bewachten Aufrufs.
typedef NS_ENUM(NSInteger, JCSaveOutcomeKind) {
    /// `executeSaveRequest:error:` gab YES zurueck; kein NSError.
    JCSaveOutcomeKindSuccess = 0,
    /// `executeSaveRequest:error:` gab NO zurueck; NSError liegt vor.
    /// Die bestehende NSError-Semantik des Aufrufers bleibt unberuehrt.
    JCSaveOutcomeKindError = 1,
    /// Eine NSException wurde von @catch erfasst. Der SaveRequest wurde
    /// moeglicherweise bereits wirksam — dieses Ergebnis ist NIE „not sent".
    JCSaveOutcomeKindException = 2,
};

/// Typisiertes Ergebnis. Traegt niemals den vollen `reason` und niemals
/// `userInfo` — nur den bereinigten Klassennamen, die Angabe, ob ein
/// `reason` vorhanden war, dessen SHA-256-Digest und einen streng
/// bereinigten Diagnosetext ohne jedes Reason-Fragment.
@interface JCSaveOutcome : NSObject

@property (nonatomic, readonly) JCSaveOutcomeKind kind;

/// Nur bei `JCSaveOutcomeKindError` gesetzt.
@property (nonatomic, readonly, nullable) NSError *error;

/// Nur bei `JCSaveOutcomeKindException`: Klassenname der Ausnahme,
/// bereinigt auf [A-Za-z0-9_] und in der Laenge begrenzt.
@property (nonatomic, readonly, nullable) NSString *exceptionName;

/// Nur bei `JCSaveOutcomeKindException`: ob `exception.reason` vorhanden war.
@property (nonatomic, readonly) BOOL reasonPresent;

/// Nur bei `JCSaveOutcomeKindException` und vorhandenem `reason`:
/// SHA-256-Hexdigest des UNVERAENDERTEN Reason-Texts (UTF-8). Der Digest
/// erlaubt spaeter den Abgleich mit einem geschuetzten Diagnoseartefakt,
/// ohne den Text selbst zu transportieren.
@property (nonatomic, readonly, nullable) NSString *reasonDigest;

/// Nur bei `JCSaveOutcomeKindException`: PII-armer Einzeiler fuer stderr —
/// enthaelt ausschliesslich den bereinigten Klassennamen, `reasonPresent`
/// und ein Digest-Praefix. NIE ein Fragment des Reason-Texts.
@property (nonatomic, readonly, nullable) NSString *sanitizedDiagnostic;

/// Ob das optionale Diagnoseartefakt (Roh-Reason) geschrieben wurde.
/// Ein Schreibfehler aendert die Ergebnisklassifikation NICHT.
@property (nonatomic, readonly) BOOL diagnosticsArtifactWritten;

/// Bei `JCSaveOutcomeKindException` immer YES: Der Prozess darf nach einer
/// gefangenen NSException nicht normal weiterarbeiten (Store-Zustand
/// undefiniert). Der Aufrufer antwortet genau einmal und beendet sich.
@property (nonatomic, readonly) BOOL processMustTerminate;

@end

/// Bewachter produktiver Aufruf: ruft `executeSaveRequest:error:` GENAU
/// EINMAL auf dem uebergebenen Store auf.
JCSaveOutcome *JCExecuteSaveRequestGuarded(CNContactStore *store,
                                           CNSaveRequest *request);

/// Testbarer Kern: fuehrt den uebergebenen Versuch genau einmal innerhalb
/// derselben @try/@catch-Grenze aus. Der Produktpfad reicht hier den echten
/// `executeSaveRequest:error:`-Aufruf hinein; der kontaktfreie Harness reicht
/// Fakes hinein (YES, NO+NSError, @throw). So wird die Grenze getestet, ohne
/// je einen echten Store anzufassen.
JCSaveOutcome *JCExecuteSaveGuardedWithAttempt(
    BOOL (NS_NOESCAPE ^attempt)(NSError *_Nullable *_Nullable error));

/// Name der Umgebungsvariable des ausdruecklichen Diagnosemodus. Nur wenn sie
/// gesetzt ist UND auf einen absoluten, existierenden, benutzereigenen
/// Ordner mit Modus 0700 zeigt, wird der Roh-Reason als exklusive
/// 0600-JSON-Datei abgelegt. Standard: nicht gesetzt — kein Artefakt.
FOUNDATION_EXPORT NSString *const JCExceptionDiagnosticsPathEnvVar;

/// Installiert den Uncaught-Exception-Diagnosehandler — genau einmal,
/// weitere Aufrufe sind wirkungslos. Ein bereits registrierter fremder
/// Handler wird gesichert und nach der eigenen Diagnose aufgerufen, nie
/// unbemerkt ersetzt.
///
/// Warum es ihn gibt: Der Save-Wurf vom 2026-08-01/02 entsteht INNERHALB
/// von Apples `performBlockAndWait`-Dispatch-Pfad. libdispatch ist eine
/// No-Throw-Grenze — beim Entwinden ueber `_dispatch_client_callout` laeuft
/// die Ausnahme in `std::terminate`, drei Ebenen unter jedem `@try` des
/// Aufrufers (Crashreport-Beleg: `_objc_terminate` im Absturzthread). Der
/// von `_objc_terminate` aufgerufene Uncaught-Handler ist der EINZIGE Ort,
/// der diese Ausnahme noch sieht.
///
/// Der Handler ist reine Letztdiagnose: er setzt den Prozess nicht fort,
/// behandelt nichts, sendet keine stdout-Antwort, beruehrt keinen Store,
/// startet keinen Retry und behauptet weder Erfolg noch `not_sent`. Er
/// schreibt eine PII-arme stderr-Zeile, fuellt — falls vorbereitet — das
/// Diagnoseartefakt ueber den bereits offenen Deskriptor und kehrt zurueck,
/// damit die normale Terminierung (SIGABRT → `child_signalled` →
/// `outcome_unknown`) unveraendert weiterlaeuft.
void JCInstallUncaughtExceptionDiagnostics(void);

NS_ASSUME_NONNULL_END

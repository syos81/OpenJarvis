# App-Prozess-Save-Spike (x86_64), 2026-08-02 — Implementierung

**Isolierter Spike, keine Produktionsintegration.** Branch
`spike/contacts-app-process-save-2026-08-02`, Worktree
`Jarvis-Next-Contacts-AppSave-Spike`, Basis `e7b45bd`. ADR-0019 bleibt
normativ; dieser Spike ist Beweisführung für eine einzige Frage.

## Ausgangslage (bewiesen)

* Fünf x86_64-Create-Livetests starben im CLI-Sidecar deterministisch an
  `NSInternalInconsistencyException`: Save auf einem
  `NSPersistentStoreCoordinator` **ohne angehängte Persistent Stores**
  (Reason digest-verifiziert erfasst, `a5246864…`).
* Der **Same-instance-Read-Warm-up ist widerlegt**: ein unmittelbar zuvor
  erfolgreicher Kontakt-Fetch auf derselben Store-Instanz änderte nichts —
  byte-identischer Wurf. Lese- und Schreibpfad sind intern getrennt.
* Alle Leseoperationen funktionieren; Kontakte.app (eigenständige,
  selbst TCC-berechtigte GUI-App) schreibt lokal problemlos.
* Architektur-Audit 2026-08-02: **TAURI APP PROCESS PREFERRED** — Jarvis.app
  ist der einzige Prozess dieses Systems, der nachweislich bereits produktiv
  mit Contacts.framework spricht (Autorisierung), und die Identität, der der
  TCC-Grant gehört.

## Was der Spike tut

Genau ein benutzergesteuerter `CNSaveRequest` **im Prozess von Jarvis.app**:
fester Payload (`contactType=person`, `givenName=ZZZ-JarvisTest-AppSave`),
Ziel ausschließlich der **eine** Container der Art `CNContainerTypeLocal`
(0 oder >1 → Abbruch ohne Save), `transactionAuthor` wortgleich zum Sidecar,
Diagnose-Fetch vor dem Save, Read-back danach. Kein Retry — nach keinem
Ausgang. Keine Backend-, Outbox- oder Datenbankbeteiligung.

## Verriegelung

* **Laufzeitfreigabe:** nur `OPENJARVIS_CONTACTS_APP_SAVE_SPIKE=1` aktiviert
  Commands und Oberfläche; sonst `disabled`, kein `CNContactStore`.
* **Vier Bindungen der Ausführung:** `user_initiated`, wörtlich einzutippende
  Bestätigungsphrase (`APP-SAVE-SPIKE JETZT AUSFÜHREN`), einmaliger Nonce aus
  `prepare`, Payload-Digest-Gleichheit (SHA-256 im Shim gebildet).
* **Einmaligkeit je App-Prozess:** `not_started → running → completed`,
  mutex-geschützt, ohne Reset; der Ausführen-Knopf sperrt sofort dauerhaft.

## Diagnose

`@try/@catch` um den einen `executeSaveRequest`; zusätzlich
`NSSetUncaughtExceptionHandler` (fremder Handler bleibt erhalten) für den
Dispatch-Wurf, den kein `@catch` erreicht. Roh-Reason ausschließlich im per
`OPENJARVIS_CONTACTS_EXCEPTION_DIAGNOSTICS_PATH` aktivierten, exklusiven
0600-Artefakt (Ordner 0700, benutzereigen, kein Symlink); öffentlich reisen
nur Klassenname und SHA-256-Digest. Beendet eine Exception den ganzen
App-Prozess, gibt es keinen Neustart des Vorgangs und keinen zweiten Save —
Crashreport und Artefakt sind die Beweise (`app_crashed`).

## Späterer Livetest (eigene Freigabe erforderlich)

x86_64 **zuerst** (dort ist der Fehler reproduzierbar), Ablauf: Gate →
Diagnoseordner → App mit beiden Variablen starten → Spike vorbereiten →
Phrase eintippen → genau einmal ausführen → Ergebnis lesen → Sichtprüfung in
Apple Kontakte → **manuelles** Löschen dort → kein Sync, kein Reconcile.

Stop-/Go danach:

* `applied` + Sichtprüfung positiv → Architekturentscheidung bestätigt;
  **ARM64-Spike** nativ wiederholen; erst nach beidem produktive Integration
  planen (eigener ADR-Nachtrag).
* erneut Null-Store (`caught_exception`/`app_crashed` mit bekanntem Digest)
  → Prozesskontext-Familie vollständig widerlegt → **Helper-App-Spike mit
  eigenem TCC-Grant** als nächster Schritt; parallel Prüfung eines
  macOS-12-Systemzustands dieses Geräts.
* jeder andere Fehler → Diagnose auswerten, kein zweiter Versuch im selben
  App-Prozess.

Keine produktive ADR-Entscheidung gilt als endgültig, bevor der
x86_64-Livetest bestanden ist.

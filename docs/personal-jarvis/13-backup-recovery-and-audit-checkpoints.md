---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-23, AV-24 (Checkpoint-Verankerung)
Zugehörige ADRs: ADR-0010
Verwandte DEC-Einträge: DEC-017, DEC-023, DEC-024
---

# 13 — Backup, Recovery und Audit-Checkpoints

## §1 Geltungsbereich

Gesichert werden alle im Speicher-Register (06 §2) mit Backup = ja geführten Speicher: `personal/jarvis.db`, Upstream-`sessions.db` (bis zur Chat-Migration), der Blob-Store, die Konfiguration (ohne Secrets) sowie die Backup-Metadaten selbst. **Nicht** Teil normaler Backups: Secrets/Keychain (separater R2-Export, §6), abgeleitete Indizes (Rebuild), technische Upstream-Speicher. Der **Backup-Kern funktioniert ab dem ersten kanonischen Datenbestand** (AV-23, DEC-024); das spätere Fachmodul „Backup & Wiederherstellung" ergänzt UI, Kataloge und Zeitpläne.

## §2 Schlüsselarchitektur

- Zufälliger **Datenverschlüsselungsschlüssel (DEK)** je Backup-Repository; Verschlüsselung AES-256-GCM.
- **Schlüsselhüllen (Envelopes) im Repository-Header:** (a) DEK für den lokalen Betrieb im **Keychain**; (b) DEK zusätzlich verschlüsselt mit einem **Recovery Key** (einmalig erzeugt, offline zu verwahren) und/oder einer **Nutzerpassphrase** (KDF: Argon2id). **Der Recovery Key selbst wird niemals automatisch in dasselbe Backup geschrieben** — nur die damit verschlüsselte Hülle liegt im Header. Format/Passphrase-Pflicht: DEC-D03.
- **Wiederherstellungsmatrix:** Mac + Keychain vorhanden ⇒ Keychain-Weg. Mac verloren, Recovery Key vorhanden ⇒ vollständige Wiederherstellung auf leerer Installation. Beides verloren ⇒ Backup planmäßig unwiederherstellbar (dokumentierte Konsequenz).
- Schlüsselrotation (Re-Keying) ist eine eigene **R2**-Operation.

## §3 SnapshotCoordinator (konsistente Mehr-Speicher-Backups)

1. **Barriere:** Das CommandBus-Gate schließt kurz die Annahme neuer Mutationen; laufende Transaktionen enden (begrenzter Timeout); Worker pausieren an sicheren Punkten (zwischen Items). Ziel-Pausendauer: Sekundenbereich.
2. **Snapshots:** jede registrierte SQLite-Datenbank konsistent über die SQLite-Backup-API bzw. `VACUUM INTO`; je Speicher werden `schema_version` und Softwareversion festgehalten.
3. **Barriere öffnen;** danach Blob-Manifest (Hash, Größe, Änderungsstand) — der inhaltsadressierte Blob-Store ist append-only, maßgeblich ist der Referenzstand der DB-Snapshots.
4. **Verschlüsseln und schreiben.**
5. **Backup-Manifest** abschließen (alle Bestandteile, Prüfsummen, Versionen und **Snapshot-Zeitpunkt je Speicher**, Audit-Chain-Head/Checkpoint, Abschlusszeit). **Erst wenn alle Bestandteile erfolgreich sind, gilt der Lauf als `complete`; sonst `failed`.** Fehlgeschlagene/unvollständige Läufe sind **nicht wiederherstellbar** und werden nie zur Wiederherstellung angeboten.

**Klarstellung Konsistenzumfang:** Die Barriere (CommandBus-Gate) pausiert die durch Personal Jarvis **kontrollierbaren Personal-Mutationen**. Nicht durch Personal Jarvis kontrollierte Upstream-Schreiber — insbesondere `sessions.db` — werden **nicht** global angehalten; jede solche SQLite-Datenbank wird über die SQLite-Backup-API bzw. einen äquivalent konsistenten DB-Snapshot **je Datenbank konsistent** gesichert, und das Gesamtmanifest hält den jeweiligen Snapshot-Zeitpunkt fest. Das Backup ist damit speicherübergreifend **vollständig**, stellt aber ausdrücklich **keine globale ACID-Transaktion über alle unabhängigen Upstream-Speicher** dar.

Die Barriere läuft zusätzlich **vor jeder Migrationsausführung** (07 §6 Nr. 4). Backup-Ziele und Aufbewahrung: DEC-D16.

## §4 Restore

Reihenfolge (verbindlich): Manifest- und Prüfsummen-Verifikation → Kompatibilitätsprüfung je Speicher (`schema_version` migrierbar) → Wiederherstellung **aller** Bestandteile in ein frisches Staging (nie in-place) → Migrationen je Speicher → Integritätsprüfungen (Fremdschlüssel, Bestände gegen Manifest) → **atomare Aktivierung** des vollständig geprüften Stands bei gestopptem Server (Verzeichnis-/Datei-Swap in einem Schritt; Altstand als Rettungskopie) → Neuaufbau der abgeleiteten Indizes → Prüfung der CredentialReferences: fehlende Keychain-Einträge werden je Konto als „erneut zu verbinden" geführt (Secrets sind nie im Backup) → Abschluss-Audit. **Niemals wird ein teilweise wiederhergestellter Mischstand aktiviert;** jede fehlgeschlagene Stufe bricht ab, ohne den Altzustand zu berühren.

## §5 Audit-Checkpoints

- **Signierte Checkpoints** des Audit-Chain-Head (Ed25519; Signaturschlüssel im Keychain): bei jedem Backup (Aufnahme ins verschlüsselte Manifest), **sofort nach jeder R2-Ausführung**, sowie zeitgesteuert.
- Zusätzlich ist ein **manueller externer Checkpoint-Export** (Datei/Ausdruck auf Offline-Medium) vorgesehen; Kadenz und Medium: DEC-D07.
- Bedrohungsmodell und Grenzen: 10 §6.

## §6 Secret-Export

Ein Export von Zugangsdaten ist von normalen Backups getrennt, ausdrücklich freigabepflichtig und als irreversibel-sicherheitskritische Operation **R2** (09 §4, 10 §1).

## §7 Restore-Drill

Der dokumentierte Wiederherstellungstest auf einer leeren Installation ist Pflichtbestandteil der Abnahme des Backup-Kerns und umfasst **ausdrücklich den Verlust des ursprünglichen Macs und der ursprünglichen Keychain** (Wiederherstellung allein über die Recovery-Hülle).

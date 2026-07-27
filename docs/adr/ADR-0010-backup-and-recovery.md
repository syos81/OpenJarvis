---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-23, AV-24 (Checkpoint-Verankerung)
Zugehörige ADRs: ADR-0003, ADR-0004
Verwandte DEC-Einträge: DEC-017, DEC-023, DEC-024; offen: DEC-D03, DEC-D07, DEC-D16
---

# ADR-0010: Backup und Recovery

- **ADR-Status:** accepted
- **Datum:** 2026-07-27

## Kontext

Ein ausschließlich im lokalen Keychain gespeicherter Backup-Schlüssel machte externe Backups beim Verlust des Macs wertlos. Bis zur Chat-Migration sind mehrere fachlich relevante Speicher gemeinsam konsistent zu sichern (jarvis.db, Upstream-sessions.db, Blob-Store, Config). Audit-Nachweisbarkeit (insbesondere R2/Trading) braucht extern verankerte Fixpunkte.

## Entscheidung

1. **Schlüsselarchitektur:** zufälliger DEK je Backup-Repository (AES-256-GCM); Hüllen: Keychain-Kopie **und** Recovery-Key- und/oder Passphrasen-Hülle (Argon2id) im Repository-Header; **der Recovery Key selbst wird nie automatisch in dasselbe Backup geschrieben**; dokumentierte Verlustmatrix (beides verloren ⇒ planmäßig unwiederherstellbar).
2. **SnapshotCoordinator:** kurze Schreib-Barriere (CommandBus-Gate, Worker an Item-Grenzen), konsistente SQLite-Snapshots (Backup-API/`VACUUM INTO`) aller registrierten Speicher, Blob-Manifest, per-Speicher schema_version/Softwareversion, abschließendes Manifest; **nur vollständig erfolgreiche Läufe (`complete`) sind wiederherstellbar**.
3. **Restore:** Verifikation → Kompatibilitätsprüfung → Staging (nie in-place) → Migrationen → Integritätsprüfung → **atomare Aktivierung** bei gestopptem Server; nie ein Mischstand; Altstand als Rettungskopie; Index-Rebuild; Konten-Re-Link (Secrets sind nie im Backup).
4. **Pflichten:** Backup-Barriere vor jeder Migration; Restore-Drill auf leerer Installation **inkl. Verlust von Mac und Keychain**; Backup-Kern funktionsfähig ab dem ersten kanonischen Datenbestand; Secret-Export getrennt und R2; Schlüsselrotation R2.
5. **Audit-Checkpoints:** signierte Chain-Head-Fixpunkte (Keychain-Schlüssel) bei jedem Backup, nach jeder R2-Ausführung und zeitgesteuert; Aufnahme in Manifeste; manueller externer Export.

## Geprüfte Alternativen

- **Backup-Schlüssel nur im Keychain** — verworfen: Geräteverlust = Totalverlust der externen Backups.
- **Recovery Key im Backup selbst** — verworfen: hebt die Verschlüsselung auf; nur die verschlüsselte Hülle liegt im Header.
- **Unabhängige Einzel-Backups je Speicher ohne Barriere** — verworfen: inkonsistente Mischstände zwischen jarvis.db, sessions.db und Blobs.
- **In-place-Restore** — verworfen: Teilfehler hinterließe einen zerstörten Aktivstand.

## Konsequenzen

Backups sind gegen Geräteverlust wiederherstellbar und mehr-speicher-konsistent; der Preis ist eine kurze Schreibpause je Lauf; Format-/Kadenz-/Ziel-Details bleiben offen (DEC-D03, DEC-D07, DEC-D16).

## Verweise

Primärdokument: 13. Regeln: AV-23, AV-24.

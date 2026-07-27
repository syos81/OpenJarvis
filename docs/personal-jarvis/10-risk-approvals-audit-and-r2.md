---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-27
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-17, AV-18, AV-19, AV-24 (Log-Aufbau/Bedrohungsmodell)
Zugehörige ADRs: ADR-0006
Verwandte DEC-Einträge: DEC-005, DEC-023
---

# 10 — Risikoklassen, Approvals, Audit und R2

## §1 Risikoklassen

- **R0** — lokal oder extern **lesend**, ohne Zustandsänderung.
- **R1** — extern **schreibend, versendend oder verändernd**.
- **R2** — **finanziell, irreversibel, sicherheitskritisch oder mit erheblichen Folgen** (dazu zählt auch die Datenlöschung eines Moduls, 07 §6).

Jede Capability-Operation deklariert ihre Klasse; zusammen mit dem Initiation-Kontext (05 §5) ergibt sich die Bestätigungsform (AV-17).

**R1 benötigt:** Capability-Prüfung · verständliche, vollständige Vorschau · explizite Bestätigung (Kontextregeln 05 §5) · Audit-Log · Ergebnisverifikation (05 §6).

**R2 benötigt zusätzlich:** separaten **dauerhaften Approval-Datensatz** (ApprovalIntent) · **deterministische Sicherheits-/Risiko-Engine** · **erneute Zustandsprüfung unmittelbar vor Ausführung** · **eindeutigen Not-Aus bzw. Abbruchpfad** · **unveränderliche Ausführungs- und Ergebnisprotokollierung**.

**Trading:** Trading-Orders sind **immer R2**. Ein Sprachmodell darf **niemals** direkt Orders platzieren oder Risikoregeln verändern (AV-18).

## §2 RiskEngine

Rein codebasierte, deterministische Regelprüfung für R2 (z. B. Instrument-Allowlist, Größen-/Tageslimits, Kontodeckung, Handelszeiten, Duplikatssperre) — **keine LLM-Beteiligung**; für Sprachmodelle unerreichbar (AV-8). Die Regeln liegen kanonisch beim besitzenden Modul (z. B. `risk_rules` bei Trading); **Regeländerungen sind selbst R2** und durchlaufen denselben Freigabefluss.

## §3 Approval-Lifecycle

Zustandsmaschine des ApprovalIntent:

`draft → validated → previewed → pending_approval → approved | denied | expired → executing → verifying → completed | failed | aborted`

- R1-Bestätigungen sind synchron am Ort der Aktion (UI-Dialog bzw. explizite Chat-Aktion; `user_direct`-Regel in 05 §5).
- R2-Freigaben laufen ausschließlich über das **Approval-Center** mit dauerhaftem Datensatz in der kanonischen DB.
- LLM-initiierte Intents parken in `pending_approval`; das Tool-Ergebnis lautet „wartet auf Freigabe"; Ausführung erst nach menschlicher Aktion.
- Vor `executing` steht bei R2 der Zustands-Recheck (Kurs-/Deckungs-/Regel-Prüfung); Abweichung ⇒ zurück nach `pending_approval` oder `aborted`.

## §4 Executor-Trennung und Not-Aus

- Getrennte Bereiche (AV-19, Warteschlangen in 11 §1): **Sync-Worker + R1-Executor** (allgemein) und **separater R2-Executor** mit eigener Warteschlange.
- **Globaler R2-Kill-Switch:** stoppt ausschließlich den R2-Executor; offene R2-Intents fallen auf `aborted`. Setzbar über UI, CLI und Konfiguration.
- Zusätzlich möglich: **konto-** bzw. **capability-bezogene Sperren** (gezieltes Pausieren) sowie ein davon unabhängiges operatives „Sync pausieren".
- Ein Trading-Not-Aus hält damit nie die übrige Synchronisation oder R1-Verarbeitung an.

## §5 Audit-Log

- `audit_log` ist **append-only und hash-verkettet** (`prev_hash`, `payload_hash`); jede Pipeline-Stufe schreibt ihr Ereignis (Bestandteil derselben Transaktion wie die Fachänderung, 11 §2).
- R2-Ausführungen protokollieren zusätzlich vollständige Request-/Response-Digests; nach jeder R2-Ausführung wird ein signierter Audit-Checkpoint erzeugt (Mechanik: 13 §5).

## §6 Bedrohungsmodell (ehrlich)

- **Die Hash-Kette schützt gegen:** nachträgliche unbemerkte Änderung, Löschung oder Umordnung von Einträgen, sofern ein vertrauenswürdiger Chain-Head bekannt ist; versehentliche Korruption; „leises" Aufräumen durch fehlerhafte Software.
- **Sie schützt nicht gegen:** einen Angreifer mit vollen Benutzerrechten, der die gesamte Kette samt Head konsistent neu schreibt; Manipulation **vor** dem Schreiben (kompromittierter Prozess); Löschung aller erreichbaren Kopien.
- **Head-Schutz:** signierte Checkpoints (Ed25519, Schlüssel im Keychain), Aufnahme in verschlüsselte Backup-Manifeste, manueller externer Export (13 §5; Kadenz/Medium: DEC-D07). Divergenz zwischen Kette und historischen Checkpoints in Offline-Kopien macht Manipulation nachweisbar; Trading-/R2-Aktionen sind darüber mindestens extern verankert belegbar.
- **Vollständige Unveränderlichkeit wird ohne externe Vertrauensinstanz ausdrücklich nicht behauptet** (AV-24).

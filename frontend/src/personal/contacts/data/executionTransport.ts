// Transport des App-Prozess-Mutationskanals (ADR-0020, Phase A).
//
// Diese Schicht ist bewusst **dumm**. Sie holt einen Auftrag, reicht ihn
// unverändert an das Tauri-Command weiter, reicht den Bericht unverändert
// zurück an das Backend. Sie berechnet keinen Digest, erfindet keinen
// Claim, deutet keinen Bericht und wählt keinen Terminalzustand: All das
// ist Sache des Kerns, und zwar deshalb, weil dies genau die Schicht ist,
// die manipuliert sein könnte.
//
// Der gesamte HTTP-Verkehr liegt im Kontakte-Client (`api.ts`) — hier steht
// nur der Ablauf.
//
// Die harte Regel: **Der Aufruf des App-Prozesses geschieht höchstens
// einmal.** Schlägt er fehl, wird er nicht wiederholt — ob dabei gesendet
// wurde, weiss niemand, und ein zweiter Aufruf könnte doppelt anwenden.
// Wiederholt werden darf ausschliesslich das Settle, mit demselben Bericht.

import { isTauri } from '../../../lib/api';
import {
  claimAppExecution,
  settleAppExecution,
} from '../api';
import type {
  ExecutionOrderV1,
  ExecutionReportV1,
  SettleResult,
} from '../api';

export type { ExecutionOrderV1, ExecutionReportV1, SettleResult };

export class TransportFehler extends Error {
  constructor(message: string, readonly code: string,
              readonly phase: 'claim' | 'tauri' | 'settle') {
    super(message);
    this.name = 'TransportFehler';
  }
}

export interface OffenesSettle {
  mutationId: string;
  claimToken: string;
  bericht: ExecutionReportV1;
}

export interface TransportErgebnis {
  settle: SettleResult | null;
  bericht: ExecutionReportV1 | null;
  /** Gesetzt, wenn ein Bericht vorliegt, das Settle aber nicht durchkam. */
  offenesSettle: OffenesSettle | null;
}

/**
 * Übergibt den Auftrag an den App-Prozess.
 *
 * Ausserhalb von Tauri (Browser, Tests) gibt es keinen App-Prozess — dann
 * entsteht ein ehrlicher `not_sent`-Bericht statt einer Fehlermeldung, die
 * das Backend nicht einordnen könnte.
 */
export async function executeInAppProcess(
  auftrag: ExecutionOrderV1,
): Promise<ExecutionReportV1> {
  if (!isTauri()) {
    return {
      schema_version: auftrag.schema_version,
      operation_id: auftrag.operation_id,
      mutation_id: auftrag.mutation_id,
      operation_type: auftrag.operation_type,
      outcome: 'not_sent',
      send_attempted: false,
      save_request_count: 0,
      readback_status: 'not_attempted',
      provider_identifier_digest: null,
      readback_revision: null,
      readback_digest: null,
      error_class: 'provider_channel_disabled_before_send',
      error_digest: null,
      diagnostic_artifact_present: false,
      provider_completed_at: null,
    };
  }
  const { invoke } = await import('@tauri-apps/api/core');
  // Der Auftrag geht **unverändert** hinüber: kein Feld wird ergänzt,
  // entfernt oder umsortiert — sonst bräche der Digest.
  return invoke<ExecutionReportV1>('personal_contacts_execute_mutation', {
    orderJson: JSON.stringify(auftrag),
  });
}

/**
 * Der vollständige Weg: Claim → App-Prozess → Settle.
 *
 * Fehlerregeln, bewusst asymmetrisch:
 *
 * * **Vor** dem Auftrag: Ein Fehler ist folgenlos — es wurde nichts
 *   beansprucht, der Aufrufer hält sich an den Backendzustand.
 * * **Nach** dem Auftrag: Kein neuer Claim, nie. Auch nicht bei einem
 *   Fehler im Aufruf des App-Prozesses — ob dabei gesendet wurde, ist
 *   unbekannt.
 * * **Nach** dem Bericht: Nur das Settle darf wiederholt werden, mit
 *   demselben Bericht. Der Aufrufer bekommt ihn dafür zurück; er lebt
 *   ausschliesslich im Speicher — ein roher Claim-Token gehört nicht in
 *   einen dauerhaften Browserspeicher.
 */
export async function fuehreAus(
  mutationId: string, confirmDelete = false,
): Promise<TransportErgebnis> {
  const auftrag = await claimAppExecution(mutationId, confirmDelete);

  let bericht: ExecutionReportV1;
  try {
    bericht = await executeInAppProcess(auftrag);
  } catch (e) {
    // Kein zweiter Versuch. Der Vorgang bleibt serverseitig in Arbeit und
    // endet über den Wiederanlauf im ungewissen Ausgang.
    throw new TransportFehler(
      e instanceof Error ? e.message : 'Der App-Prozess antwortete nicht',
      'response_lost', 'tauri');
  }

  try {
    const settle = await settleAppExecution(
      mutationId, auftrag.claim_token, bericht);
    return { settle, bericht, offenesSettle: null };
  } catch {
    return {
      settle: null,
      bericht,
      offenesSettle: { mutationId, claimToken: auftrag.claim_token, bericht },
    };
  }
}

/** Wiederholt **nur** das Settle — nie den Aufruf des App-Prozesses. */
export function wiederholeSettle(offen: OffenesSettle): Promise<SettleResult> {
  return settleAppExecution(offen.mutationId, offen.claimToken, offen.bericht);
}

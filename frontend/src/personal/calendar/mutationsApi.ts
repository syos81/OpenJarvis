// Schreibpfad des Kalendermoduls (B3 P1) — bewusst eine EIGENE Datei.
//
// `api.ts` liest; dieser Client trägt die einzelfreigegebenen Mutationen:
// normativ DEC-069 — Kalenderschreiben produktiv zugelassen:
// einzelfreigegebene Mutationen über den getrennten Schreibpfad
// (docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md).
//
// Die Schicht ist bewusst dumm (wie der Kontakte-Transport,
// `contacts/data/executionTransport.ts`): kein Digest wird hier gerechnet,
// kein Bericht gedeutet, kein Terminalzustand gewählt — das ist Sache des
// Servers, weil genau diese Schicht manipuliert sein könnte.

import { getBase, authHeaders, isTauri } from '../../lib/api';

const PREFIX = '/v1/personal/calendar';

/** Der geschlossene Feldsatz eines `create` — genau diese sechs. */
export interface TerminFelder {
  title: string | null;
  starts_at_utc: string;
  ends_at_utc: string;
  is_all_day: boolean;
  location: string | null;
  notes: string | null;
}

/** Die Vorschau, wie der SERVER sie gebaut hat. Freigegeben wird, was man
 *  sieht — deshalb zeigt die Oberfläche ausschliesslich diese Werte. */
export interface MutationsVorschau {
  command: string;
  calendar_display_name: string;
  title: string | null;
  starts_at_utc: string;
  ends_at_utc: string;
  is_all_day: boolean;
  location: string | null;
}

export interface VorbereiteterVorgang {
  mutation_id: string;
  approval_id: string;
  state: string;
  payload_digest: string;
  preview: MutationsVorschau;
  preview_digest: string;
}

/** Der Auftrag aus dem Claim — er reist UNVERÄNDERT in den App-Prozess. */
export interface KalenderExecutionOrder {
  schema_version: number;
  operation_id: string;
  mutation_id: string;
  /** Der einzige Rohwert des Kanals — nur für die Dauer eines Versuchs. */
  claim_token: string;
  operation_type: 'create' | 'update' | 'delete';
  payload_digest: string;
  preview_digest: string;
  canonical_payload: Record<string, unknown>;
  issued_at: string;
  expires_at: string;
  provider_target: { provider_calendar_id: string; event_identifier: string | null };
  expected_fingerprint: string | null;
}

/** Der typisierte Bericht des App-Prozesses (`calendar_write.rs`). */
export interface KalenderExecutionReport {
  schema_version: number;
  operation_id: string;
  mutation_id: string;
  operation_type: string;
  /** `unknown` heisst „möglicherweise gesendet" — nie „vermutlich gut". */
  outcome: 'applied' | 'not_sent' | 'unknown';
  send_attempted: boolean;
  save_request_count: number;
  readback_status: 'confirmed' | 'absent_confirmed' | 'unavailable' | 'not_checked';
  readback_event: Record<string, unknown> | null;
  provider_identifier: string | null;
  fingerprint_checked: boolean;
  fingerprint_matched: boolean | null;
  error_class: string | null;
  error_digest: string | null;
  provider_completed_at: string | null;
}

export interface SettleErgebnis {
  mutation_id: string;
  state: string;
  outcome: string | null;
  idempotent: boolean;
  error_class: string | null;
}

/** Der entscheidende Mensch — derselbe Wert wie im Kontaktmodul. */
const ENTSCHEIDER = 'lukas';

async function hole<T>(pfad: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${PREFIX}${pfad}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    // Wie in `api.ts`: kein Servertext wird durchgereicht — er könnte einen
    // Termininhalt tragen. Die Statusklasse genügt der Oberfläche.
    throw new Error(`calendar_api_${res.status}`);
  }
  return (await res.json()) as T;
}

/** Bereitet EINE Mutation vor. Es wird nichts gesendet. */
export function bereiteVor(providerCalendarId: string,
                           felder: TerminFelder): Promise<VorbereiteterVorgang> {
  return hole('/mutations', {
    method: 'POST',
    body: JSON.stringify({
      command: 'create',
      provider_calendar_id: providerCalendarId,
      fields: felder,
    }),
  });
}

/** Menschliche Freigabe. Verbraucht wird sie erst beim Claim. */
export function gibFrei(mutationId: string): Promise<{ mutation_id: string; state: string }> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ decision_actor: ENTSCHEIDER }),
  });
}

/** Bricht aus `prepared`/`approved` ab — es wurde nichts gesendet. */
export function bricheAb(mutationId: string): Promise<{ mutation_id: string; state: string }> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ decision_actor: ENTSCHEIDER }),
  });
}

/** Beansprucht EINEN Ausführungsversuch. Nie automatisch wiederholen. */
export function beanspruche(mutationId: string): Promise<KalenderExecutionOrder> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/claim-app-execution`,
              { method: 'POST' });
}

/** Meldet den Bericht. Darf mit DEMSELBEN Bericht wiederholt werden. */
export function schliesseAb(mutationId: string, claimToken: string,
                            bericht: KalenderExecutionReport): Promise<SettleErgebnis> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}/settle-app-execution`, {
    method: 'POST',
    body: JSON.stringify({ report: bericht, claim_token: claimToken }),
  });
}

/** Zustand und Vorschau eines Vorgangs. Reine Projektion. */
export function ladeMutation(mutationId: string): Promise<Record<string, unknown>> {
  return hole(`/mutations/${encodeURIComponent(mutationId)}`);
}

/**
 * Übergibt den Auftrag an den App-Prozess — HÖCHSTENS EINMAL.
 *
 * Der Auftrag geht als unveränderter JSON-Text hinüber: kein Feld wird
 * ergänzt, entfernt oder umsortiert — sonst bräche der Digest. Ausserhalb
 * von Tauri gibt es keinen App-Prozess; das ist ein ehrlicher Fehler, kein
 * stiller Ersatzweg.
 */
export async function fuehreAus(orderJson: string): Promise<KalenderExecutionReport> {
  if (!isTauri()) {
    throw new Error('app_process_unavailable');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<KalenderExecutionReport>('personal_calendar_execute_mutation',
                                         { orderJson });
}

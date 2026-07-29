// API-Client des Kontakte-Moduls.
//
// Nutzt bewusst den bestehenden Basis-Client (`getBase`, `authHeaders`) statt
// eines zweiten Transportwegs. Es gibt keinen direkten Provider- oder
// Sidecar-Aufruf aus dem Frontend: jede Mutation läuft über
// /v1/personal/contacts und dort über den ApplicationCommandBus.
//
// Was hier niemals im UI-State landet: Sync-Cursor, Change-History-Token,
// Roh-Payloads. Der `write_target` ist die einzige Provider-Kennung, die
// überhaupt herauskommt — sie ist Pflicht, weil sonst nur über einen Namen
// gezielt werden könnte, und genau das ist verboten.

import { getBase, authHeaders } from '../../lib/api';

const PREFIX = '/v1/personal/contacts';

export type FieldState = 'present' | 'absent' | 'unavailable_by_capability';

export interface FieldAvailability {
  field_name: string;
  state: FieldState;
}

export interface LabeledValue {
  id: string;
  position: number;
  label_raw: string | null;
  label_normalized: string | null;
  value: string | null;
  extra: Record<string, unknown>;
}

export interface ContactSummary {
  id: string;
  display_name: string;
  organization_name: string | null;
  contact_type: string;
  is_me_card: boolean;
  field_completeness: string;
  sync_state: string;
  conflict_state: string | null;
  roles: string[];
  provider_account_ids: string[];
  email_count: number;
  phone_count: number;
  address_count: number;
  has_unavailable_fields: boolean;
}

export interface ContactPage {
  items: ContactSummary[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ContactDetail {
  id: string;
  workspace_id: string;
  display_name: string;
  contact_type: string;
  given_name: string | null;
  middle_name: string | null;
  family_name: string | null;
  nickname: string | null;
  organization_name: string | null;
  department_name: string | null;
  job_title: string | null;
  is_me_card: boolean;
  birthday_year: number | null;
  birthday_month: number | null;
  birthday_day: number | null;
  local_revision: number;
  sync_state: string;
  conflict_state: string | null;
  field_completeness: string;
  updated_at: string | null;
  thumbnail_blob_ref: string | null;
  emails: LabeledValue[];
  phones: LabeledValue[];
  postal_addresses: LabeledValue[];
  urls: LabeledValue[];
  dates: LabeledValue[];
  social_profiles: LabeledValue[];
  instant_messages: LabeledValue[];
  relations: LabeledValue[];
  roles: string[];
  field_availability: FieldAvailability[];
  provider_accounts: string[];
  containers: string[];
  write_target: string | null;
  unified_read_only: boolean;
}

export interface RoleCount {
  role: string;
  count: number;
}

export interface FieldChange {
  field_name: string;
  previous: unknown;
  planned: unknown;
}

export interface PreparedMutation {
  mutation_id: string;
  approval_id: string;
  state: string;
  payload_digest: string;
  preview_digest: string;
  reused: boolean;
  command: string;
  target_provider_identifier: string | null;
  container_identifier: string | null;
  target_label: string | null;
  changes: FieldChange[];
  warnings: string[];
}

export interface Mutation {
  mutation_id: string;
  command: string;
  state: string;
  outcome: string | null;
  initiation_context: string;
  actor: string;
  correlation_id: string;
  provider_account_id: string;
  target_contact_id: string | null;
  target_display_name: string | null;
  container_identifier: string | null;
  expected_revision: string | null;
  attempt_count: number;
  last_error_code: string | null;
  created_at: string;
  approved_at: string | null;
  completed_at: string | null;
  approval_id: string | null;
  approval_state: string | null;
  approval_expires_at: string | null;
  requires_reconcile: boolean;
  needs_manual_decision: boolean;
}

export interface MutationDetail extends Mutation {
  changes: FieldChange[];
  payload_digest: string;
  preview_digest: string;
}

export interface Approval {
  approval_id: string;
  mutation_id: string;
  command: string;
  state: string;
  initiation_context: string;
  actor: string;
  correlation_id: string;
  requested_at: string;
  expires_at: string;
  decided_at: string | null;
  decision_actor: string | null;
  preview_digest: string;
  is_expired: boolean;
}

export interface Capabilities {
  read_supported: boolean;
  create_supported: boolean;
  update_supported: boolean;
  delete_supported: boolean;
  change_history_supported: boolean;
  full_diff_supported: boolean;
  notes_supported: boolean;
  unified_read_supported: boolean;
  unified_link_supported: boolean;
  me_card_writable: boolean;
  unavailable_fields: string[];
  mutations_available: boolean;
}

export type AuthorizationState =
  | 'notDetermined' | 'restricted' | 'denied' | 'authorized' | 'unknown';

export interface Authorization {
  status: AuthorizationState;
  can_request: boolean;
  bridge_available: boolean;
  reason: string;
}

/** Ergebnis eines Laufs — ausschliesslich aggregiert, nie ein Kontaktwert. */
export interface SyncRun {
  mode: 'initial_import' | 'full_diff' | 'delta';
  succeeded: boolean;
  containers: number;
  read: number;
  imported: number;
  updated: number;
  tombstoned: number;
  unchanged: number;
  events_processed: number;
  cursor_present: boolean;
  cursor_advanced: boolean;
  requires_full_diff: boolean;
  error_class: string | null;
  retryable: boolean;
  detail: string;
  completed_at: string;
}

/**
 * Sync-Zustand, wie ihn die Oberfläche braucht.
 *
 * Der Server liefert mehr Felder — Konto- und Containerkennung,
 * `key_set_version`, `circuit_state`. Sie werden hier bewusst **nicht**
 * typisiert und damit auch nicht benutzt: was nicht im Typ steht, landet
 * nicht im UI-State und kann nicht versehentlich angezeigt werden.
 */
export interface SyncStatus {
  mode: string;
  has_cursor: boolean;
  cursor_taken_at: string | null;
  last_full_diff_at: string | null;
  updated_at: string;
}

export interface ReconcileResult {
  mutation_id: string;
  verdict: string;
  state: string;
  provider_identifier: string | null;
  detail: string | null;
}

export class ContactsApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;

  constructor(status: number, code: string, message: string, retryable = false) {
    super(message);
    this.name = 'ContactsApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

let workspace = 'default';

export function setWorkspace(id: string): void {
  workspace = id;
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return authHeaders({ 'X-Personal-Workspace': workspace, ...extra });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${getBase()}${PREFIX}${path}`, {
    ...init,
    headers: headers(
      init.body ? { 'Content-Type': 'application/json' } : {},
    ) as HeadersInit,
  });
  if (!response.ok) {
    let code = 'internal';
    let message = `HTTP ${response.status}`;
    let retryable = false;
    try {
      const body = await response.json();
      const detail = body?.detail ?? body;
      if (detail && typeof detail === 'object') {
        code = detail.code ?? code;
        message = detail.message ?? message;
        retryable = Boolean(detail.retryable);
      }
    } catch {
      // Antwort ohne JSON-Körper: die Statuszeile bleibt die Aussage.
    }
    throw new ContactsApiError(response.status, code, message, retryable);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined | null>): string {
  const teile = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return teile.length ? `?${teile.join('&')}` : '';
}

// ── Lesen ──────────────────────────────────────────────────────────────────
export function listContacts(params: {
  search?: string; role?: string; providerAccountId?: string;
  cursor?: string; limit?: number;
} = {}): Promise<ContactPage> {
  return request<ContactPage>(
    query({
      search: params.search, role: params.role,
      provider_account_id: params.providerAccountId,
      cursor: params.cursor, limit: params.limit,
    }),
  );
}

export function getContact(id: string): Promise<ContactDetail> {
  return request<ContactDetail>(`/${encodeURIComponent(id)}`);
}

export function listCategories(): Promise<RoleCount[]> {
  return request<RoleCount[]>('/categories');
}

export function getCapabilities(): Promise<Capabilities> {
  return request<Capabilities>('/capabilities');
}

// ── Autorisierung und manueller Lese-Sync ──────────────────────────────────
//
// Diese drei Funktionen sind die einzigen im Client, die serverseitig einen
// Sidecar starten können. Keine wird beim Laden der Seite aufgerufen — der
// Statusabruf ist lesend und löst keinen Systemdialog aus, die beiden anderen
// hängen an einem Knopfdruck.

/** Liest den Berechtigungsstatus. Löst **keinen** macOS-Dialog aus. */
export function getAuthorization(): Promise<Authorization> {
  return request<Authorization>('/authorization');
}

/**
 * Fordert die Berechtigung an — ausschliesslich auf ausdrückliche
 * Nutzeraktion. `user_initiated` ist serverseitig Pflicht und muss `true`
 * sein; es gibt keinen Aufruf ohne Körper.
 */
export function requestAuthorization(): Promise<Authorization> {
  return request<Authorization>('/authorization/request', {
    method: 'POST',
    body: JSON.stringify({ user_initiated: true }),
  });
}

/** Ein ausdrücklich ausgelöster, ausschliesslich lesender Lauf. */
export function runSync(): Promise<SyncRun> {
  return request<SyncRun>('/sync', { method: 'POST' });
}

export function getSyncStatus(): Promise<SyncStatus[]> {
  return request<SyncStatus[]>('/sync/status');
}

// ── Lokale Kategorien (R0, rein lokal) ─────────────────────────────────────
export function assignRole(contactId: string, role: string): Promise<{ contact_id: string; roles: string[] }> {
  return request(`/${encodeURIComponent(contactId)}/roles`, {
    method: 'POST',
    body: JSON.stringify({ role }),
  });
}

export function removeRole(contactId: string, role: string): Promise<{ contact_id: string; roles: string[] }> {
  return request(
    `/${encodeURIComponent(contactId)}/roles/${encodeURIComponent(role)}`,
    { method: 'DELETE' },
  );
}

// ── Mutationen vorbereiten (nie ausführen) ─────────────────────────────────
export interface PrepareBase {
  idempotencyKey: string;
  correlationId: string;
  providerAccountId: string;
}

export function prepareCreate(
  input: PrepareBase & { containerIdentifier: string; fields: Record<string, unknown> },
): Promise<PreparedMutation> {
  return request<PreparedMutation>('', {
    method: 'POST',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
      provider_account_id: input.providerAccountId,
      container_identifier: input.containerIdentifier,
      fields: input.fields,
    }),
  });
}

export function prepareUpdate(
  contactId: string,
  input: PrepareBase & {
    targetProviderIdentifier: string;
    expectedRevision: string | null;
    fields: Record<string, unknown>;
  },
): Promise<PreparedMutation> {
  return request<PreparedMutation>(`/${encodeURIComponent(contactId)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
      provider_account_id: input.providerAccountId,
      target_provider_identifier: input.targetProviderIdentifier,
      expected_revision: input.expectedRevision,
      fields: input.fields,
    }),
  });
}

export function prepareDelete(
  contactId: string,
  input: PrepareBase & {
    targetProviderIdentifier: string;
    expectedRevision: string | null;
  },
): Promise<PreparedMutation> {
  return request<PreparedMutation>(`/${encodeURIComponent(contactId)}/delete`, {
    method: 'POST',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
      provider_account_id: input.providerAccountId,
      target_provider_identifier: input.targetProviderIdentifier,
      expected_revision: input.expectedRevision,
    }),
  });
}

// ── Freigaben und Status ───────────────────────────────────────────────────
export function listMutations(params: { state?: string; limit?: number } = {}): Promise<Mutation[]> {
  return request<Mutation[]>(`/mutations${query({ state: params.state, limit: params.limit })}`);
}

export function getMutation(id: string): Promise<MutationDetail> {
  return request<MutationDetail>(`/mutations/${encodeURIComponent(id)}`);
}

export function listApprovals(params: { state?: string; includeExpired?: boolean } = {}): Promise<Approval[]> {
  return request<Approval[]>(
    `/approvals${query({
      state: params.state,
      include_expired: params.includeExpired === false ? 'false' : undefined,
    })}`,
  );
}

function decide(mutationId: string, aktion: string, decisionActor?: string): Promise<Approval> {
  return request<Approval>(
    `/mutations/${encodeURIComponent(mutationId)}/${aktion}`,
    {
      method: 'POST',
      body: decisionActor ? JSON.stringify({ decision_actor: decisionActor }) : undefined,
    },
  );
}

export const approveMutation = (id: string, actor: string) => decide(id, 'approve', actor);
export const rejectMutation = (id: string, actor: string) => decide(id, 'reject', actor);
export const cancelMutation = (id: string, actor: string) => decide(id, 'cancel', actor);
export const expireMutation = (id: string) => decide(id, 'expire');

/** Gleicht ausschließlich lesend ab. Es gibt bewusst kein „erneut senden". */
export function reconcileMutation(id: string): Promise<ReconcileResult> {
  return request<ReconcileResult>(
    `/mutations/${encodeURIComponent(id)}/reconcile`, { method: 'POST' },
  );
}

// API-Client des Kontakte-Moduls.
//
// Nutzt bewusst den bestehenden Basis-Client (`getBase`, `authHeaders`) statt
// eines zweiten Transportwegs. Es gibt keinen direkten Provider- oder
// Sidecar-Aufruf aus dem Frontend: jede Mutation läuft über
// /v1/personal/contacts und dort über den ApplicationCommandBus.
//
// Was hier niemals im UI-State landet: Sync-Cursor, Change-History-Token,
// Roh-Payloads — und seit ADR-0025 auch keine Provider-Kennung mehr. Die
// Oberfläche zielt über die lokale `contact_id` bzw. eine maskierte
// `container_ref`; das Backend löst beides intern auf.

import { getBase, authHeaders, isTauri } from '../../lib/api';

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
  /** Maskierte Kontoreferenzen — die UI braucht nur ihre Anzahl. */
  account_refs: string[];
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
  /** Providerherkunft ausschliesslich maskiert (ADR-0025). */
  account_refs: string[];
  container_refs: string[];
  provider_type: string;
  /** Ob dieser Kontakt Ziel einer Mutation sein kann. Gezielt wird über `id`. */
  writable: boolean;
  /** Lokale Revision als Konfliktbedingung — keine Apple-Kennung. */
  revision: string;
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
  /** Lokale Zielkennung — bei `create` erst nach der Ausführung bekannt. */
  target_contact_id: string | null;
  container_ref: string | null;
  /** Art des Zielablageorts — Teil der informierten Freigabe (§8 A). */
  container_type: string;
  /**
   * Lesbarer Name des Zielablageorts **aus dem Bestand**. `null` heisst „noch
   * nicht gelesen" — die Fläche zeigt das offen und setzt nie die Kennung an
   * seine Stelle. Nichts davon wird hier berechnet.
   */
  container_name: string | null;
  /** Wie viele Kontakte dort liegen. Kontext, nicht Kategorie. */
  container_contact_count: number | null;
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
  provider_type: string;
  account_ref: string;
  target_contact_id: string | null;
  target_display_name: string | null;
  container_ref: string | null;
  /** Art des Zielablageorts — Teil der informierten Freigabe (§8 A). */
  container_type: string;
  /** Lesbarer Name aus dem Bestand. `null` heisst „noch nicht gelesen". */
  container_name: string | null;
  /** Anzahl im Zielablageort. Kontext, nicht Kategorie. */
  container_contact_count: number | null;
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
  /**
   * Was freigegeben wird. Der Freigabeknopf sitzt an dieser Liste — ohne
   * Zielangabe wäre die Zustimmung nicht informiert (§8 A).
   */
  target_display_name: string | null;
  container_ref: string | null;
  container_type: string;
  /** Lesbarer Name aus dem Bestand. `null` heisst „noch nicht gelesen". */
  container_name: string | null;
  /** Anzahl im Zielablageort. Kontext, nicht Kategorie. */
  container_contact_count: number | null;
  /** Nutzlastbindung — der Beleg braucht sie neben `preview_digest`. */
  payload_digest: string;
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
  /** Satz für den Menschen — nie ein Klassenname. */
  reason: string;
  /** Stabile Vertragskennung; leer, wenn nichts schiefging. */
  technical_code: string;
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
 * Der Server liefert mehr Felder — `account_ref`, `container_ref`,
 * `provider_type`, `key_set_version`, `circuit_state`. Sie werden hier
 * bewusst **nicht** typisiert und damit auch nicht benutzt: was nicht im Typ
 * steht, landet nicht im UI-State und kann nicht versehentlich angezeigt
 * werden.
 *
 * Rohe Konto- oder Containerkennungen liefert der Server seit dem
 * 2026-07-31 gar nicht mehr; diese zweite Schranke bleibt trotzdem.
 */
export interface SyncStatus {
  mode: string;
  cursor_present: boolean;
  cursor_taken_at: string | null;
  last_full_diff_at: string | null;
  requires_full_diff: boolean;
  updated_at: string;
}

export interface ReconcileResult {
  mutation_id: string;
  verdict: string;
  state: string;
  contact_id: string | null;
  detail: string | null;
}

/** Ergebnis eines Ausführungsversuchs — aggregiert, ohne Providerkennung. */
export interface ExecutionResult {
  mutation_id: string;
  state: string;
  outcome: string | null;
  error_code: string | null;
  retryable: boolean;
  attempt_count: number;
  contact_id: string | null;
  pending_local_catchup: boolean;
}

/** Feldvertrag v1 — die geschlossene Feldmenge einer Neuanlage. */
export interface LabeledValueIn {
  label: string | null;
  value: string;
}

export interface ContactFieldsIn {
  contact_type?: 'person' | 'organization';
  given_name?: string;
  middle_name?: string;
  family_name?: string;
  nickname?: string;
  organization_name?: string;
  department_name?: string;
  job_title?: string;
  birthday?: { year?: number | null; month: number; day: number };
  emails?: LabeledValueIn[];
  phones?: LabeledValueIn[];
  urls?: LabeledValueIn[];
}

export class ContactsApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;
  /** Stabile, PII-freie Vertragskennung des Fehlerbildes. Nie ein Pfad. */
  readonly technicalCode: string;

  constructor(status: number, code: string, message: string, retryable = false,
              technicalCode = '') {
    super(message);
    this.name = 'ContactsApiError';
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.technicalCode = technicalCode;
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
    // Fallback ohne Serverangabe: eine Statuszeile ist wenig, aber sie ist
    // ehrlich — und sie ist kein Klassenname aus dem Serverinneren.
    let message = `Der Server hat mit HTTP ${response.status} geantwortet.`;
    let retryable = response.status >= 500;
    let technicalCode = `http_${response.status}`;
    try {
      const body = await response.json();
      const detail = body?.detail ?? body;
      if (detail && typeof detail === 'object') {
        code = detail.code ?? code;
        message = detail.message ?? message;
        retryable = Boolean(detail.retryable);
        technicalCode = detail.technical_code ?? code;
      }
    } catch {
      // Antwort ohne JSON-Körper: die Statuszeile bleibt die Aussage.
    }
    throw new ContactsApiError(response.status, code, message, retryable,
                               technicalCode);
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
 * Rohes Ergebnis des nativen App-Kommandos, inklusive PII-armer
 * Laufzeitdiagnostik.
 *
 * Die Zusatzfelder sind kein Beiwerk: `CNErrorDomain/100` allein sagt nicht,
 * ob der Aufruf auf dem Main Thread lief, ob die App im Vordergrund war, ob
 * das Bundle die Usage Description trägt und welche TCC-Identität der Prozess
 * hatte. Genau diese vier Angaben unterscheiden die Fehlerbilder.
 */
interface NativeAuthOutcome {
  status: AuthorizationState;
  granted: boolean;
  prompt_attempted: boolean;
  error_domain: string | null;
  error_code: number | null;
  bundle_identifier: string;
  has_usage_description: boolean;
  app_active: boolean;
  called_on_main_thread: boolean;
  entity_type: number;
  status_before: AuthorizationState;
  callback_ran: boolean;
  callback_count: number;
}

/** Verdichtet die Diagnostik zu einer PII-armen Kennung. */
function diagnoseKennung(o: NativeAuthOutcome): string {
  return [
    `bundle=${o.bundle_identifier || 'unbekannt'}`,
    `usage=${o.has_usage_description}`,
    `active=${o.app_active}`,
    `mainthread=${o.called_on_main_thread}`,
    `entity=${o.entity_type}`,
    `vorher=${o.status_before}`,
    `callback=${o.callback_ran}/${o.callback_count}`,
    `nachher=${o.status}`,
  ].join(' ');
}

/**
 * Fordert die Berechtigung an — **aus dem App-Prozess**, nicht über den Server.
 *
 * Der Weg über den Sidecar war architektonisch falsch: macOS rechnet einen
 * TCC-Dialog dem verantwortlichen Prozess zu, und der Sidecar wird über `uv`
 * und `python` erreicht — beides ohne App-Bundle. `requestAccess` kam von dort
 * mit `CNErrorDomain/100` zurück, ohne dass je ein Dialog erschien.
 *
 * Jetzt ruft der Tauri-Hauptprozess selbst — er *ist* OpenJarvis.app, trägt
 * die Usage Description und steht im Vordergrund. Aufgerufen wird das nur aus
 * einem Klickhandler; es gibt keinen zweiten Aufrufer und keine Wiederholung.
 *
 * Ausserhalb der App (reiner Browser) gibt es keinen Prozess, dem ein Dialog
 * zugeordnet werden könnte. Dann wird das ehrlich gesagt, statt einen Aufruf
 * abzusetzen, der nur wieder undurchsichtig scheitern würde.
 */
export async function requestAuthorization(): Promise<Authorization> {
  if (!isTauri()) {
    throw new ContactsApiError(
      503, 'unavailable',
      'Der Berechtigungsdialog kann nur in der Personal-Jarvis-App angefordert '
      + 'werden. Im Browser gibt es keinen Prozess, dem macOS ihn zuordnen könnte.',
      false, 'tcc_prompt_unavailable:requires_desktop_app');
  }
  let roh: NativeAuthOutcome;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    roh = await invoke<NativeAuthOutcome>('personal_contacts_request_authorization');
  } catch (e) {
    throw new ContactsApiError(
      503, 'unavailable',
      'Der Berechtigungsdialog konnte nicht geöffnet werden.',
      true, 'tcc_prompt_unavailable:ipc_failed');
  }

  if (roh.error_domain) {
    const grund = roh.error_domain === 'timeout'
      ? 'authorization_request:request_timeout'
      : `authorization_request:tcc_request_rejected:${roh.error_domain}/${roh.error_code}`;
    throw new ContactsApiError(
      503, 'unavailable',
      roh.error_domain === 'timeout'
        ? 'Die Entscheidung im Systemdialog blieb aus.'
        : 'Das System hat die Berechtigungsanfrage abgelehnt.',
      true, `${grund} · ${diagnoseKennung(roh)}`);
  }

  return {
    status: roh.status,
    can_request: roh.status === 'notDetermined',
    bridge_available: true,
    reason: '',
    technical_code: '',
  };
}

/** Ein ausdrücklich ausgelöster, ausschliesslich lesender Lauf. */
export function runSync(): Promise<SyncRun> {
  return request<SyncRun>('/sync', { method: 'POST' });
}

/**
 * Wählbare Ablageorte für eine Neuanlage — **ausschliesslich maskiert**.
 *
 * Bewusst eine eigene, enge Sicht auf `/sync/status`: der Statustyp oben
 * blendet die Referenzen absichtlich aus, weil die Statusanzeige sie nicht
 * braucht. Der Anlagedialog braucht sie — aber auch er sieht nur Kürzel.
 */
export interface ContainerOption {
  container_ref: string;
  account_ref: string;
  provider_type: string;
  /**
   * Art des Ablageorts (`local`, `cardDAV`, `exchange`, …). Sie ist die
   * Angabe, an der sich ein Ziel bewusst wählen lässt — nicht Reihenfolge und
   * nicht Grösse. `unknown`, solange kein Lauf sie erhoben hat.
   */
  container_type: string;
  /**
   * Letzter Lauf, der den Zustand fortgeschrieben hat. `null` heisst: dieser
   * Ablageort ist nur aus dem Containerinventar bekannt und wurde nie
   * vollständig gelesen — dann fehlen Fähigkeiten und Feldzustände, und das
   * Backend weist ihn als Ziel ohnehin zurück.
   */
  last_successful_run_at: string | null;
}

export function listContainers(): Promise<ContainerOption[]> {
  return request<ContainerOption[]>('/sync/status').then(
    // Die Regel steht hier und nicht in der Ansicht: ein Ablageort, der kein
    // gültiges Ziel ist, wird gar nicht erst angeboten. Ein angebotener und
    // dann abgelehnter Eintrag lädt zum Probieren ein — und Probieren ist bei
    // einer Neuanlage genau das Falsche.
    (o) => o.filter((e) => e.last_successful_run_at !== null),
  );
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
}

/**
 * Bereitet eine Neuanlage vor. Zielt über eine **maskierte** `container_ref`;
 * rohe Apple-Kennungen kennt die Oberfläche nicht mehr.
 */
export function prepareCreate(
  input: PrepareBase & { containerRef: string; fields: ContactFieldsIn },
): Promise<PreparedMutation> {
  return request<PreparedMutation>('', {
    method: 'POST',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
      container_ref: input.containerRef,
      fields: input.fields,
    }),
  });
}

/** Ziel ist die lokale `contactId`; das Backend löst sie intern auf. */
export function prepareUpdate(
  contactId: string,
  input: PrepareBase & {
    expectedRevision: string;
    fields: Record<string, unknown>;
  },
): Promise<PreparedMutation> {
  return request<PreparedMutation>(`/${encodeURIComponent(contactId)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
      expected_revision: input.expectedRevision,
      fields: input.fields,
    }),
  });
}

export function prepareDelete(
  contactId: string,
  input: PrepareBase & { expectedRevision: string },
): Promise<PreparedMutation> {
  return request<PreparedMutation>(`/${encodeURIComponent(contactId)}/delete`, {
    method: 'POST',
    body: JSON.stringify({
      idempotency_key: input.idempotencyKey,
      correlation_id: input.correlationId,
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

/**
 * Führt eine **freigegebene** Mutation aus — die einzige Stelle, an der etwas
 * zum Provider geht. Bewusst ein eigener Aufruf: eine Freigabe führt nichts
 * aus. `user_initiated` ist Pflicht und steht im Rumpf, nicht in der URL.
 */
export function executeMutation(id: string): Promise<ExecutionResult> {
  return request<ExecutionResult>(
    `/mutations/${encodeURIComponent(id)}/execute`,
    { method: 'POST', body: JSON.stringify({ user_initiated: true }) },
  );
}

/**
 * Schliesst einen ungewissen Ausgang nach **externer** Prüfung ab.
 *
 * Der Fall: der Provider hat technisch nicht geantwortet, und der Mensch hat
 * ausserhalb von Jarvis nachgesehen. Diese Route berührt den Provider nicht
 * und ermöglicht **niemals** einen zweiten Send — sie hält eine Beobachtung
 * fest und schliesst den Vorgang ab.
 */
export function resolveOutcomeNotObserved(id: string): Promise<ExecutionResult> {
  return request<ExecutionResult>(
    `/mutations/${encodeURIComponent(id)}/resolve-outcome`,
    {
      method: 'POST',
      body: JSON.stringify({
        user_initiated: true,
        decision: 'not_observed',
        evidence: 'manual_provider_inspection',
      }),
    },
  );
}

/** Gleicht ausschließlich lesend ab. Es gibt bewusst kein „erneut senden". */
export function reconcileMutation(id: string): Promise<ReconcileResult> {
  return request<ReconcileResult>(
    `/mutations/${encodeURIComponent(id)}/reconcile`, { method: 'POST' },
  );
}

// ── App-Prozess-Ausführungskanal (ADR-0026, Phase A) ────────────────────────
//
// Der Kanal hat drei Berührungspunkte mit dem Server: Fähigkeiten lesen,
// **einen** Versuch beanspruchen, **einen** Bericht melden. Sie liegen hier,
// weil hier der gesamte HTTP-Verkehr des Moduls liegt — der Transportdienst
// darüber ist reine Ablauflogik ohne eigene Netzschicht.

export interface AppChannelCapabilities {
  schema_version: number;
  channel: 'app_process';
  /**
   * Warum nichts geht. In jedem Build dieses Stands `disabled`;
   * `fake_debug` lebt nur im Backendprozess und erreicht diese Antwort nie.
   */
  channel_mode: 'disabled' | 'fake_debug' | 'native_create';
  /**
   * Bauzustand, nicht Erlaubnis: Der native Create-Pfad ist einkompiliert.
   * Getrennt von `create_supported`, weil „vorhanden" und „darf" zwei
   * verschiedene Aussagen sind.
   */
  native_create_available: boolean;
  /** `true` erst mit gültiger Schreibfreigabe — sonst durchweg `false`. */
  create_supported: boolean;
  update_supported: boolean;
  delete_supported: boolean;
  /** In Phase A immer `false`: Der Transport steht, der native Save nicht. */
  provider_write_enabled: boolean;
  architecture: string;
  app_version: string;
  native_bridge_version: string;
}

/**
 * Der Satz, den die Statusoberfläche für Phase A zeigt.
 *
 * Bewusst hier und nicht in einer Komponente: Die Aussage ist ein Vertrag,
 * kein Text. Sie darf sich nicht zwischen zwei Ansichten unterscheiden.
 */
export const PHASE_A_KANALTEXT =
  'Transport vorbereitet, Provider-Schreiben deaktiviert';

/**
 * Ob eine Operation angeboten werden darf — dieselbe Konjunktion wie im Kern.
 *
 * Das Frontend kann damit nichts freischalten: Es liest ausschliesslich die
 * Serverantwort. Ein `create_supported: true` ohne `provider_write_enabled`
 * ist ein widersprüchlicher Handshake und ergibt hier `false`.
 */
export function kanalErlaubt(
  caps: AppChannelCapabilities | null | undefined,
  operation: 'create' | 'update' | 'delete',
): boolean {
  if (!caps || caps.channel !== 'app_process') return false;
  const modi = ['disabled', 'fake_debug', 'native_create'];
  if (!modi.includes(caps.channel_mode)) return false;
  if (!caps.provider_write_enabled) return false;
  const feld = operation === 'create' ? caps.create_supported
    : operation === 'update' ? caps.update_supported
      : caps.delete_supported;
  return feld === true;
}

export interface ExecutionOrderV1 {
  schema_version: number;
  operation_id: string;
  mutation_id: string;
  /** Der einzige Rohwert des Kanals — nur für die Dauer eines Versuchs. */
  claim_token: string;
  operation_type: 'create' | 'update' | 'delete';
  payload_digest: string;
  preview_digest: string;
  canonical_payload: Record<string, unknown>;
  readback_requirements: Record<string, unknown>;
  issued_at: string;
  expires_at: string;
  mutation_contract_version: number;
  field_contract_version: number;
  transaction_author: string;
  expected_revision: string | null;
  provider_target: Record<string, string | null>;
}

export interface ExecutionReportV1 {
  schema_version: number;
  operation_id: string;
  mutation_id: string;
  operation_type: 'create' | 'update' | 'delete';
  outcome: 'applied' | 'not_sent' | 'outcome_unknown';
  send_attempted: boolean;
  save_request_count: number;
  readback_status: 'confirmed' | 'absent_confirmed' | 'failed' | 'not_attempted';
  provider_identifier_digest: string | null;
  /**
   * Die rohe Providerkennung. Sie reist ausschliesslich im Settle-Rumpf zum
   * Backend, das sie für die External-ID braucht — nie in Oberfläche, Log
   * oder normaler API. Das Frontend reicht sie durch und liest sie nie.
   */
  provider_identifier?: string | null;
  /** Der gelesene Zustand in kanonischer v1-Form; der Kern rechnet daraus. */
  readback_contact?: Record<string, unknown> | null;
  readback_revision: string | null;
  readback_digest: string | null;
  error_class: string | null;
  error_digest: string | null;
  diagnostic_artifact_present: boolean;
  provider_completed_at: string | null;
}

export interface SettleResult {
  mutation_id: string;
  state: string;
  outcome: string | null;
  error_class: string | null;
  idempotent: boolean;
}

export function getAppChannel(): Promise<AppChannelCapabilities> {
  return request<AppChannelCapabilities>('/app-channel');
}

/** Beansprucht **einen** Versuch. Nie automatisch wiederholen. */
export function claimAppExecution(
  mutationId: string, confirmDelete = false,
): Promise<ExecutionOrderV1> {
  // `confirm_delete` ist die **zweite** Handlung des Menschen (R2,
  // ADR-0026 §8.3, DEC-053) — sie ersetzt die Freigabe nicht. Der Server
  // weist einen Löschanspruch ohne sie ab; hier wird sie nur weitergereicht,
  // nie erfunden.
  return request<ExecutionOrderV1>(
    `/mutations/${encodeURIComponent(mutationId)}/claim-app-execution`,
    {
      method: 'POST',
      body: JSON.stringify(confirmDelete
        ? { user_initiated: true, confirm_delete: true }
        : { user_initiated: true }),
    });
}

/** Meldet den Bericht. Darf mit **demselben** Bericht wiederholt werden. */
export function settleAppExecution(
  mutationId: string, claimToken: string, report: ExecutionReportV1,
): Promise<SettleResult> {
  return request<SettleResult>(
    `/mutations/${encodeURIComponent(mutationId)}/settle-app-execution`,
    {
      method: 'POST',
      body: JSON.stringify({
        user_initiated: true, claim_token: claimToken, report,
      }),
    });
}

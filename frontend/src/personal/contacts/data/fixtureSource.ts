// Demo-Quelle: derselbe Vertrag wie die API-Quelle, rein im Speicher.
//
// Kein einziger Aufruf des Kontakte-Clients, kein Netz, kein Sync, keine
// produktive Mutation. Vorgänge und Freigaben sind Fake-Objekte; darunter
// bewusst je einer in `awaiting_approval`, `outcome_unknown` und
// `manual_decision_required`, damit alle Jarvis-Zustände ohne produktive
// Daten sichtbar und testbar sind. „Ausführen" gibt es im Demo-Modus nicht:
// die Capability bleibt aus, exakt wie im gesperrten Produktivbetrieb.

import { ContactsApiError } from '../api';
import type {
  Approval, Authorization, Capabilities, ContactDetail, ContactSummary,
  FieldChange, Mutation, MutationDetail, PreparedMutation, RoleCount,
  SyncStatus,
} from '../api';
import {
  syntheticDetail, syntheticKategorien, syntheticSummaries,
} from './fixtures';
import type { ContactsDataSource } from './source';

// Update/Delete sind im Demo-Modus absichtlich AN: der Bearbeitungsmodus
// soll ohne produktive Daten voll erlebbar sein. Alles endet in
// Fake-Vorgaengen; `execute` lehnt grundsaetzlich ab.
const CAPS: Capabilities = {
  read_supported: true,
  create_supported: false,
  update_supported: true,
  delete_supported: true,
  change_history_supported: false,
  full_diff_supported: true,
  notes_supported: false,
  unified_read_supported: true,
  unified_link_supported: false,
  me_card_writable: false,
  unavailable_fields: ['note'],
  mutations_available: true,
};

interface FakeVorgang extends MutationDetail { }

let laufendeNummer = 0;

function fakeMutation(teil: Partial<MutationDetail> & {
  command: string; state: string;
}): FakeVorgang {
  laufendeNummer += 1;
  const nr = laufendeNummer;
  return {
    mutation_id: `demo-m-${nr}`,
    outcome: null,
    initiation_context: 'demo_mode',
    actor: 'demo',
    correlation_id: `demo-c-${nr}`,
    provider_type: 'apple_contacts',
    account_ref: 'A-demo-lokal',
    target_contact_id: null,
    target_display_name: null,
    container_ref: 'C-demo-1',
    expected_revision: null,
    attempt_count: teil.state === 'outcome_unknown' ? 1 : 0,
    last_error_code: teil.state === 'outcome_unknown' ? 'child_signalled' : null,
    created_at: '2026-08-02 12:00',
    approved_at: null,
    completed_at: null,
    approval_id: `demo-a-${nr}`,
    approval_state: teil.state === 'awaiting_approval' ? 'requested' : null,
    approval_expires_at: null,
    requires_reconcile: teil.state === 'outcome_unknown',
    needs_manual_decision: teil.state === 'manual_decision_required',
    changes: [],
    payload_digest: `demo-digest-${nr}`,
    preview_digest: `demo-preview-${nr}`,
    ...teil,
  };
}

export function fixtureDataSource(anzahl: number): ContactsDataSource {
  const kontakte = syntheticSummaries(anzahl);
  const beispiel = kontakte.find((k) => !k.is_me_card) ?? kontakte[0];

  // Drei stehende Fake-Vorgänge für die Jarvis-Zustandsflächen.
  const vorgaenge: FakeVorgang[] = [
    fakeMutation({
      command: 'update', state: 'awaiting_approval',
      target_contact_id: beispiel?.id ?? null,
      target_display_name: beispiel?.display_name ?? null,
      changes: [{
        field_name: 'organization_name',
        previous: beispiel?.organization_name ?? null,
        planned: 'Beispiel GmbH (Demo)',
      }],
    }),
    fakeMutation({
      command: 'update', state: 'outcome_unknown',
      target_display_name: 'Tessa Testmann',
      changes: [{ field_name: 'job_title', previous: null, planned: 'Referenzfigur' }],
    }),
    fakeMutation({
      command: 'delete', state: 'manual_decision_required',
      target_display_name: 'Quirin Quasiecht',
    }),
  ];

  const freigaben = (): Approval[] => vorgaenge
    .filter((m) => m.state === 'awaiting_approval')
    .map((m) => ({
      approval_id: m.approval_id ?? '',
      mutation_id: m.mutation_id,
      command: m.command,
      state: 'awaiting_approval',
      initiation_context: m.initiation_context,
      actor: m.actor,
      correlation_id: m.correlation_id,
      requested_at: m.created_at,
      expires_at: '2026-08-03 12:00',
      decided_at: null,
      decision_actor: null,
      preview_digest: m.preview_digest,
      is_expired: false,
    }));

  const finde = (id: string): FakeVorgang => {
    const m = vorgaenge.find((v) => v.mutation_id === id);
    if (!m) throw new Error('Demo-Vorgang nicht gefunden.');
    return m;
  };

  const entscheiden = (id: string, zustand: string) => {
    const m = finde(id);
    m.state = zustand;
    m.approval_state = zustand;
    return Promise.resolve({ mutation_id: id, state: zustand });
  };

  return {
    art: 'fixtures',
    ladeAlle: () => Promise.resolve(kontakte),
    suche: (query) => {
      const q = query.trim().toLowerCase();
      if (!q) return Promise.resolve(kontakte);
      return Promise.resolve(kontakte.filter((k) => {
        if (k.display_name.toLowerCase().includes(q)) return true;
        if (k.organization_name?.toLowerCase().includes(q)) return true;
        const d = syntheticDetail(k.id);
        return d.emails.some((w) => w.value?.toLowerCase().includes(q))
          || d.phones.some((w) => (w.value ?? '').replace(/\s/g, '')
            .includes(q.replace(/\s/g, '')));
      }));
    },
    detail: (id) => Promise.resolve(syntheticDetail(id)),
    kategorien: () => Promise.resolve(syntheticKategorien(kontakte)),
    capabilities: () => Promise.resolve(CAPS),
    authorization: () => Promise.resolve<Authorization>({
      status: 'authorized',
      can_request: false,
      bridge_available: true,
      reason: 'Demo-Modus: Es besteht keine Verbindung zu Apple Kontakte.',
      technical_code: '',
    }),
    syncStatus: () => Promise.resolve<SyncStatus[]>([]),

    assignRole: (id, role) => {
      const k = kontakte.find((v) => v.id === id);
      if (k && !k.roles.includes(role)) k.roles = [...k.roles, role];
      return Promise.resolve({ roles: k?.roles ?? [] });
    },
    removeRole: (id, role) => {
      const k = kontakte.find((v) => v.id === id);
      if (k) k.roles = k.roles.filter((r) => r !== role);
      return Promise.resolve({ roles: k?.roles ?? [] });
    },
    prepareUpdate: (id, { fields }) => {
      const ziel = kontakte.find((k) => k.id === id);
      const changes: FieldChange[] = Object.entries(fields)
        .map(([field_name, planned]) => ({ field_name, previous: null, planned }));
      const m = fakeMutation({
        command: 'update', state: 'awaiting_approval',
        target_contact_id: id,
        target_display_name: ziel?.display_name ?? null,
        changes,
      });
      vorgaenge.unshift(m);
      return Promise.resolve<PreparedMutation>({
        mutation_id: m.mutation_id,
        approval_id: m.approval_id ?? '',
        state: m.state,
        payload_digest: m.payload_digest,
        preview_digest: m.preview_digest,
        reused: false,
        command: m.command,
        target_contact_id: id,
        container_ref: m.container_ref,
        target_label: ziel?.display_name ?? null,
        changes,
        warnings: ['Demo-Modus: Dieser Vorgang existiert nur im Speicher.'],
      });
    },
    prepareDelete: (id) => {
      const ziel = kontakte.find((k) => k.id === id);
      const m = fakeMutation({
        command: 'delete', state: 'awaiting_approval',
        target_contact_id: id,
        target_display_name: ziel?.display_name ?? null,
      });
      vorgaenge.unshift(m);
      return Promise.resolve<PreparedMutation>({
        mutation_id: m.mutation_id,
        approval_id: m.approval_id ?? '',
        state: m.state,
        payload_digest: m.payload_digest,
        preview_digest: m.preview_digest,
        reused: false,
        command: 'delete',
        target_contact_id: id,
        container_ref: m.container_ref,
        target_label: ziel?.display_name ?? null,
        changes: [],
        warnings: ['Demo-Modus: Dieser Vorgang existiert nur im Speicher.'],
      });
    },

    listApprovals: () => Promise.resolve(freigaben()),
    listMutations: () => Promise.resolve<Mutation[]>([...vorgaenge]),
    getMutation: (id) => Promise.resolve(finde(id)),
    approve: (id) => entscheiden(id, 'approved'),
    reject: (id) => entscheiden(id, 'rejected'),
    cancel: (id) => entscheiden(id, 'cancelled'),
    expire: (id) => entscheiden(id, 'expired'),
    // Ausführen ist im Demo-Modus nicht erreichbar (Capabilities aus); der
    // Vertrag verlangt die Methode trotzdem — sie lehnt ab statt zu raten.
    execute: () => Promise.reject(new ContactsApiError(
      409, 'demo_mode', 'Im Demo-Modus wird nichts ausgeführt.', false,
      'demo_execute_blocked',
    )),
    reconcile: (id) => entscheiden(id, 'manually_resolved_not_applied'),
    resolveNotObserved: (id) => entscheiden(id, 'manually_resolved_not_applied'),
  };
}

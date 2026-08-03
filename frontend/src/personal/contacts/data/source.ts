// Datenquelle der Kontakte-Oberfläche.
//
// Der Workspace kennt nur diesen Vertrag. Die API-Quelle delegiert 1:1 an
// den bestehenden Client (api.ts) — sie erfindet keine neue Mutations- oder
// Sync-Logik. Die Demo-Quelle (fixtureSource.ts) implementiert denselben
// Vertrag rein im Speicher mit synthetischen Daten.
//
// Ausführen/Abgleichen/Abschliessen bleiben Teil des Vertrags, damit die
// Statusfläche in beiden Betriebsarten identisch aussieht. Im API-Betrieb
// führen sie exakt die bestehenden, abgesicherten Wege aus; im Demo-Betrieb
// verändern sie nur Fake-Vorgänge.

import * as api from '../api';
import type {
  Approval, Authorization, Capabilities, ContactDetail, ContactSummary,
  Mutation, MutationDetail, PreparedMutation, RoleCount, SyncStatus,
} from '../api';

export type QuellenArt = 'api' | 'fixtures';

export interface ContactsDataSource {
  art: QuellenArt;
  /** Lädt den vollständigen lokalen Kontaktbestand (alle Seiten). */
  ladeAlle(): Promise<ContactSummary[]>;
  /**
   * Suche über den Kontakte-Datenzustand. Die Demo-Quelle filtert rein
   * lokal (Name, Organisation, E-Mail, Telefon); die API-Quelle nutzt die
   * Suche des lokalen Servers über dieselben Felder — beides ohne
   * Providerzugriff und ohne Sync.
   */
  suche(query: string): Promise<ContactSummary[]>;
  detail(id: string): Promise<ContactDetail>;
  kategorien(): Promise<RoleCount[]>;
  capabilities(): Promise<Capabilities>;
  authorization(): Promise<Authorization>;
  syncStatus(): Promise<SyncStatus[]>;

  /** Lokale Kategorien — sie verlassen den Mac nie. */
  assignRole(id: string, role: string): Promise<{ roles: string[] }>;
  removeRole(id: string, role: string): Promise<{ roles: string[] }>;

  prepareUpdate(id: string, args: {
    expectedRevision: string; fields: Record<string, string>;
  }): Promise<PreparedMutation>;
  prepareDelete(id: string, args: { expectedRevision: string }): Promise<PreparedMutation>;

  listApprovals(): Promise<Approval[]>;
  listMutations(): Promise<Mutation[]>;
  getMutation(id: string): Promise<MutationDetail>;
  approve(id: string, actor: string): Promise<unknown>;
  reject(id: string, actor: string): Promise<unknown>;
  cancel(id: string, actor: string): Promise<unknown>;
  expire(id: string): Promise<unknown>;
  execute(id: string): Promise<unknown>;
  reconcile(id: string): Promise<unknown>;
  resolveNotObserved(id: string): Promise<unknown>;
}

function neueId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `id-${Date.now()}-${Math.random()}`;
}

/** Produktionsquelle: der bestehende Kontakte-Client, vollständig geseitet. */
export function apiDataSource(): ContactsDataSource {
  const alleSeiten = async (search?: string): Promise<ContactSummary[]> => {
    const items: ContactSummary[] = [];
    let cursor: string | undefined;
    // Obergrenze gegen Endlosschleifen bei fehlerhaftem Cursor.
    for (let seite = 0; seite < 200; seite += 1) {
      const p = await api.listContacts({ search, cursor, limit: 200 });
      items.push(...p.items);
      if (!p.has_more || !p.next_cursor) break;
      cursor = p.next_cursor;
    }
    return items;
  };
  return {
    art: 'api',
    ladeAlle: () => alleSeiten(),
    suche: (query) => alleSeiten(query || undefined),
    detail: (id) => api.getContact(id),
    kategorien: () => api.listCategories(),
    capabilities: () => api.getCapabilities(),
    authorization: () => api.getAuthorization(),
    syncStatus: () => api.getSyncStatus(),
    assignRole: (id, role) => api.assignRole(id, role),
    removeRole: (id, role) => api.removeRole(id, role),
    prepareUpdate: (id, { expectedRevision, fields }) => api.prepareUpdate(id, {
      idempotencyKey: neueId(), correlationId: neueId(),
      expectedRevision, fields,
    }),
    prepareDelete: (id, { expectedRevision }) => api.prepareDelete(id, {
      idempotencyKey: neueId(), correlationId: neueId(), expectedRevision,
    }),
    listApprovals: () => api.listApprovals(),
    listMutations: () => api.listMutations(),
    getMutation: (id) => api.getMutation(id),
    approve: (id, actor) => api.approveMutation(id, actor),
    reject: (id, actor) => api.rejectMutation(id, actor),
    cancel: (id, actor) => api.cancelMutation(id, actor),
    expire: (id) => api.expireMutation(id),
    execute: (id) => api.executeMutation(id),
    reconcile: (id) => api.reconcileMutation(id),
    resolveNotObserved: (id) => api.resolveOutcomeNotObserved(id),
  };
}

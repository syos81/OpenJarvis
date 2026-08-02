// @vitest-environment jsdom
//
// Interaktionstests der Kontakte-Seite.
//
// Diese Datei schliesst die Lücke aus Gate D: dort war ereignisgesteuertes
// Verhalten nur typgeprüft, nicht belegt. Hier wird die Seite wirklich
// gerendert und wirklich bedient — Tastatur inbegriffen.
//
// Der API-Client ist gemockt. Das ist kein Selbstzweck: es belegt zugleich,
// dass die Seite **ausschliesslich** über diesen Client spricht. Gäbe es
// irgendwo einen direkten `fetch`, würde er hier ins Leere laufen und der
// Test fehlschlagen.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('./api', async () => {
  const echt = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...echt,
    getAuthorization: vi.fn(),
    requestAuthorization: vi.fn(),
    runSync: vi.fn(),
    getSyncStatus: vi.fn(),
    listContacts: vi.fn(),
    listCategories: vi.fn(),
    getContact: vi.fn(),
    getCapabilities: vi.fn(),
    assignRole: vi.fn(),
    removeRole: vi.fn(),
    prepareUpdate: vi.fn(),
    prepareDelete: vi.fn(),
    prepareCreate: vi.fn(),
    listMutations: vi.fn(),
    getMutation: vi.fn(),
    listApprovals: vi.fn(),
    approveMutation: vi.fn(),
    rejectMutation: vi.fn(),
    cancelMutation: vi.fn(),
    expireMutation: vi.fn(),
    reconcileMutation: vi.fn(),
    resolveOutcomeNotObserved: vi.fn(),
    listContainers: vi.fn(),
    appSaveSpikeStatus: vi.fn(),
    appSaveSpikePrepare: vi.fn(),
    appSaveSpikeExecute: vi.fn(),
  };
});

import ContactsPage from './ContactsPage';
import * as api from './api';
import { ContactsApiError } from './api';

const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

// ── Fixtures: erfunden, keine echten Kontaktdaten ──────────────────────────
const zusammenfassung = (id: string, name: string, extra = {}) => ({
  id, display_name: name, organization_name: null, contact_type: 'person',
  is_me_card: false, field_completeness: 'complete', sync_state: 'synced',
  conflict_state: null, roles: [], account_refs: ['A-9f2c11'],
  email_count: 1, phone_count: 0, address_count: 0,
  has_unavailable_fields: false, ...extra,
});

const detail = (id: string, name: string, extra = {}) => ({
  id, workspace_id: 'default', display_name: name, contact_type: 'person',
  given_name: name, middle_name: null, family_name: null, nickname: null,
  organization_name: null, department_name: null, job_title: null,
  is_me_card: false, birthday_year: null, birthday_month: null,
  birthday_day: null, local_revision: 1, sync_state: 'synced',
  conflict_state: null, field_completeness: 'complete', updated_at: null,
  thumbnail_blob_ref: null, emails: [], phones: [], postal_addresses: [],
  urls: [], dates: [], social_profiles: [], instant_messages: [],
  relations: [], roles: [],
  field_availability: [{ field_name: 'note', state: 'unavailable_by_capability' }],
  account_refs: ['A-9f2c11'], container_refs: ['C-1b3d99'],
  provider_type: 'apple_contacts', writable: true, revision: '1',
  unified_read_only: true, ...extra,
});

const seite = (items: unknown[], extra = {}) => ({
  items, next_cursor: null, has_more: false, ...extra,
});

const lauf = (extra = {}) => ({
  mode: 'initial_import', succeeded: true, containers: 1, read: 12,
  imported: 12, updated: 0, tombstoned: 0, unchanged: 0, events_processed: 0,
  cursor_present: true, cursor_advanced: true, requires_full_diff: false,
  error_class: null, retryable: false, detail: '',
  completed_at: '2026-07-29T10:00:00+00:00', ...extra,
});

const CAPS = {
  read_supported: true, create_supported: false, update_supported: false,
  delete_supported: false, change_history_supported: true,
  full_diff_supported: true, notes_supported: false,
  unified_read_supported: true, unified_link_supported: false,
  me_card_writable: false, unavailable_fields: ['note'],
  mutations_available: false,
};

function standard() {
  mock.getAuthorization.mockResolvedValue({
    status: 'authorized', can_request: false, bridge_available: true, reason: '',
  });
  mock.getSyncStatus.mockResolvedValue([]);
  mock.listContacts.mockResolvedValue(seite([zusammenfassung('k-1', 'Alpha Test')]));
  mock.listCategories.mockResolvedValue([]);
  mock.getCapabilities.mockResolvedValue(CAPS);
  mock.getContact.mockResolvedValue(detail('k-1', 'Alpha Test'));
  mock.listApprovals.mockResolvedValue([]);
  mock.listMutations.mockResolvedValue([]);
  mock.listContainers.mockResolvedValue([]);
  mock.appSaveSpikeStatus.mockResolvedValue({ enabled: false, phase: 'not_started' });
}

beforeEach(() => {
  vi.clearAllMocks();
  standard();
});

afterEach(() => { vi.restoreAllMocks(); });

const nutzer = () => userEvent.setup();

async function seiteRendern() {
  render(<ContactsPage />);
  await screen.findByText('Alpha Test');
}

// ═══ Laden, Leere, Fehler ═══════════════════════════════════════════════════
describe('Zustände der Übersicht', () => {
  it('lädt Kontakte und zeigt sie an', async () => {
    await seiteRendern();
    expect(screen.getByText('Alpha Test')).toBeInTheDocument();
    expect(mock.listContacts).toHaveBeenCalled();
  });

  it('zeigt einen Ladezustand, bevor Daten da sind', async () => {
    let loesen: (v: unknown) => void = () => {};
    mock.listContacts.mockReturnValue(new Promise((r) => { loesen = r; }));
    render(<ContactsPage />);
    expect(await screen.findByText(/werden geladen/i)).toBeInTheDocument();
    loesen(seite([]));
  });

  it('zeigt einen erklärten Leerzustand statt einer leeren Fläche', async () => {
    mock.listContacts.mockResolvedValue(seite([]));
    render(<ContactsPage />);
    expect(await screen.findByText(/Keine Kontakte/i)).toBeInTheDocument();
  });

  it('zeigt Fehler sichtbar und als Alarm an', async () => {
    mock.listContacts.mockRejectedValue(
      new ContactsApiError(500, 'internal', 'Datenbank nicht erreichbar'));
    render(<ContactsPage />);
    const alarm = await screen.findByRole('alert');
    expect(within(alarm).getByText(/Datenbank nicht erreichbar/)).toBeInTheDocument();
  });

  it('lädt nach einem Fehler auf Knopfdruck erneut', async () => {
    const u = nutzer();
    mock.listContacts.mockRejectedValueOnce(
      new ContactsApiError(500, 'internal', 'kaputt'));
    render(<ContactsPage />);
    await screen.findByRole('alert');
    mock.listContacts.mockResolvedValue(seite([zusammenfassung('k-1', 'Alpha Test')]));
    await u.click(screen.getByRole('button', { name: /Erneut laden/i }));
    expect(await screen.findByText('Alpha Test')).toBeInTheDocument();
  });
});

// ═══ Suche, Filter, Pagination ══════════════════════════════════════════════
describe('Suche, Filter und Pagination', () => {
  it('reicht den Suchbegriff an die API weiter', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.type(screen.getByLabelText(/durchsuchen/i), 'alpha');
    await waitFor(() => {
      expect(mock.listContacts).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'alpha' }));
    });
  });

  it('filtert nach Kategorie und hebt die Auswahl wieder auf', async () => {
    const u = nutzer();
    mock.listCategories.mockResolvedValue([{ role: 'Mieter', count: 1 }]);
    await seiteRendern();
    const chip = await screen.findByRole('button', { name: /Mieter/ });

    await u.click(chip);
    await waitFor(() => {
      expect(mock.listContacts).toHaveBeenCalledWith(
        expect.objectContaining({ role: 'Mieter' }));
    });
    expect(chip).toHaveAttribute('aria-pressed', 'true');

    await u.click(chip);
    await waitFor(() => expect(chip).toHaveAttribute('aria-pressed', 'false'));
  });

  it('lädt weitere Seiten nach und hängt sie an', async () => {
    const u = nutzer();
    mock.listContacts.mockResolvedValueOnce(
      seite([zusammenfassung('k-1', 'Alpha Test')],
            { next_cursor: 'c-2', has_more: true }));
    render(<ContactsPage />);
    await screen.findByText('Alpha Test');

    mock.listContacts.mockResolvedValueOnce(
      seite([zusammenfassung('k-2', 'Beta Test')]));
    await u.click(screen.getByRole('button', { name: /Weitere laden/i }));

    expect(await screen.findByText('Beta Test')).toBeInTheDocument();
    expect(screen.getByText('Alpha Test')).toBeInTheDocument();
    expect(mock.listContacts).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: 'c-2' }));
  });

  it('bietet ohne weitere Seiten keinen Nachladeknopf an', async () => {
    await seiteRendern();
    expect(screen.queryByRole('button', { name: /Weitere laden/i })).toBeNull();
  });
});

// ═══ Detail ═════════════════════════════════════════════════════════════════
describe('Kontaktdetail', () => {
  it('öffnet einen Kontakt und zeigt ihn', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    await waitFor(() => expect(mock.getContact).toHaveBeenCalledWith('k-1'));
    expect(await screen.findByRole('button', { name: /Zurück/i })).toBeInTheDocument();
  });

  it('behandelt ein gesperrtes Feld nie als leer', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    expect(await screen.findByText(/nicht lesbar/i)).toBeInTheDocument();
    // Der entscheidende Punkt: das Feld ist nicht als „leer" ausgewiesen.
    const badge = screen.getByText(/nicht lesbar/i);
    expect(badge.getAttribute('title')).toMatch(/nicht als leer/);
  });

  it('kehrt zur Liste zurück', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    await u.click(await screen.findByRole('button', { name: /Zurück/i }));
    expect(await screen.findByLabelText(/durchsuchen/i)).toBeInTheDocument();
  });

  it('fügt eine lokale Kategorie hinzu und entfernt sie wieder', async () => {
    const u = nutzer();
    mock.assignRole.mockResolvedValue({ contact_id: 'k-1', roles: ['Mieter'] });
    mock.removeRole.mockResolvedValue({ contact_id: 'k-1', roles: [] });
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));

    const feld = await screen.findByLabelText(/Neue Kategorie/i);
    await u.type(feld, 'Mieter');
    await u.click(screen.getByRole('button', { name: /^Hinzufügen$/i }));
    await waitFor(() => expect(mock.assignRole).toHaveBeenCalledWith('k-1', 'Mieter'));

    await u.click(await screen.findByRole('button', { name: /Mieter entfernen/i }));
    await waitFor(() => expect(mock.removeRole).toHaveBeenCalledWith('k-1', 'Mieter'));
  });
});

// ═══ Berechtigung ═══════════════════════════════════════════════════════════
describe('Sync-Status ohne rohe Kennungen', () => {
  // Der Server liefert seit dem 2026-07-31 nur noch maskierte Kürzel. Die
  // Oberfläche braucht davon einzig den Zeitstempel — dieser Test hält beides
  // fest: dass sie mit dem gehärteten Vertrag arbeitet und dass kein Kürzel
  // im sichtbaren Text landet.
  const gehaertet = {
    mode: 'delta',
    cursor_present: true,
    cursor_taken_at: '2026-07-31T09:00:00+00:00',
    last_full_diff_at: null,
    requires_full_diff: false,
    updated_at: '2026-07-31T11:30:00+00:00',
  };

  it('zeigt den letzten Abgleich aus dem gehärteten Vertrag', async () => {
    mock.getSyncStatus.mockResolvedValue([gehaertet]);
    await seiteRendern();
    expect(await screen.findByText(/Zuletzt abgeglichen/)).toBeInTheDocument();
  });

  it('zeigt weder Kürzel noch Providerkennung an', async () => {
    mock.getSyncStatus.mockResolvedValue([
      { ...gehaertet, account_ref: 'A-9f2c11', container_ref: 'C-1b3d99',
        provider_type: 'apple_contacts', key_set_version: 'v1',
        circuit_state: 'closed' },
    ]);
    await seiteRendern();
    const text = document.body.textContent ?? '';
    expect(text).not.toContain('C-1b3d99');
    expect(text).not.toContain('A-9f2c11');
    expect(text).not.toContain('ABAccount');
  });
});

describe('Berechtigung', () => {
  it('fragt beim Öffnen der Seite nur den Status ab', async () => {
    await seiteRendern();
    expect(mock.getAuthorization).toHaveBeenCalledTimes(1);
    expect(mock.requestAuthorization).not.toHaveBeenCalled();
    expect(mock.runSync).not.toHaveBeenCalled();
  });

  it('zeigt „noch nicht entschieden" mit Erlaubnisknopf', async () => {
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true, reason: '',
    });
    await seiteRendern();
    expect(screen.getByTestId('auth-status')).toHaveTextContent(/Noch nicht entschieden/);
    expect(screen.getByRole('button', { name: /Zugriff auf Kontakte erlauben/i }))
      .toBeInTheDocument();
  });

  it('fordert die Berechtigung erst auf Klick an', async () => {
    const u = nutzer();
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true, reason: '',
    });
    mock.requestAuthorization.mockResolvedValue({
      status: 'authorized', can_request: false, bridge_available: true, reason: '',
    });
    await seiteRendern();
    expect(mock.requestAuthorization).not.toHaveBeenCalled();

    await u.click(screen.getByRole('button', { name: /Zugriff auf Kontakte erlauben/i }));
    await waitFor(() => expect(mock.requestAuthorization).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/Zugriff erlaubt/)).toBeInTheDocument();
  });

  it.each([
    ['denied', /Zugriff abgelehnt/, /Systemeinstellungen/],
    ['restricted', /Zugriff eingeschränkt/, /Richtlinie/],
  ])('zeigt %s klar an und bietet keinen Knopf', async (status, titel, hinweis) => {
    mock.getAuthorization.mockResolvedValue({
      status, can_request: false, bridge_available: true, reason: '',
    });
    await seiteRendern();
    expect(screen.getByTestId('auth-status')).toHaveTextContent(titel);
    expect(screen.getByText(hinweis, { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /erlauben/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /synchronisieren/i })).toBeNull();
  });

  it('rät den Status nie, wenn die Brücke fehlt', async () => {
    // Seit dem Fehlervertrag zeigt die Seite den Satz des Servers statt
    // eines pauschalen „nicht verfügbar" — das sagt mehr und ist genauso
    // PII-frei.
    mock.getAuthorization.mockResolvedValue({
      status: 'unknown', can_request: false, bridge_available: false,
      reason: 'Die Kontakte-Bruecke wurde nicht gefunden.',
      technical_code: 'bridge_not_found',
    });
    await seiteRendern();
    expect(screen.getByTestId('auth-status')).toHaveTextContent(/Status unbekannt/);
    expect(screen.getByText(/wurde nicht gefunden/i)).toBeInTheDocument();
  });

  it('sperrt den Knopf während der laufenden Anfrage', async () => {
    const u = nutzer();
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true, reason: '',
    });
    let loesen: (v: unknown) => void = () => {};
    mock.requestAuthorization.mockReturnValue(new Promise((r) => { loesen = r; }));
    await seiteRendern();

    const knopf = screen.getByRole('button', { name: /erlauben/i });
    await u.click(knopf);
    await waitFor(() => expect(knopf).toBeDisabled());
    await u.click(knopf);
    await u.click(knopf);
    expect(mock.requestAuthorization).toHaveBeenCalledTimes(1);

    loesen({ status: 'authorized', can_request: false, bridge_available: true, reason: '' });
    await waitFor(() => expect(mock.requestAuthorization).toHaveBeenCalledTimes(1));
  });

  it('zeigt einen Fehler bei der Anfrage sichtbar an', async () => {
    const u = nutzer();
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true, reason: '',
    });
    mock.requestAuthorization.mockRejectedValue(
      new ContactsApiError(503, 'unavailable', 'Brücke nicht startbar', true));
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    expect(await screen.findByText(/Brücke nicht startbar/)).toBeInTheDocument();
  });
});

// ═══ Manueller Abgleich ═════════════════════════════════════════════════════
describe('Manueller Abgleich', () => {
  it('läuft nie von selbst', async () => {
    await seiteRendern();
    expect(mock.runSync).not.toHaveBeenCalled();
  });

  it('bietet den Knopf nur bei erteilter Berechtigung an', async () => {
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true, reason: '',
    });
    await seiteRendern();
    expect(screen.queryByRole('button', { name: /synchronisieren/i })).toBeNull();
  });

  it('gleicht auf Klick ab und zeigt aggregierte Zahlen', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(lauf({ imported: 12, containers: 2, read: 12 }));
    await seiteRendern();

    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    const ergebnis = await screen.findByTestId('sync-ergebnis');
    expect(ergebnis).toHaveTextContent(/Erstimport abgeschlossen/);
    expect(ergebnis).toHaveTextContent(/2 Container/);
    expect(ergebnis).toHaveTextContent(/12 neu/);
  });

  it('zeigt keinen Cursor und keinen Identifier an', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(lauf());
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    await screen.findByTestId('sync-ergebnis');
    const text = document.body.textContent ?? '';
    for (const verboten of ['cursor', 'token', 'raw-', 'apple-local', 'con-1']) {
      expect(text.toLowerCase()).not.toContain(verboten.toLowerCase());
    }
  });

  it('lädt die Liste nach erfolgreichem Abgleich neu', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(lauf());
    await seiteRendern();
    const vorher = mock.listContacts.mock.calls.length;

    mock.listContacts.mockResolvedValue(
      seite([zusammenfassung('k-1', 'Alpha Test'),
             zusammenfassung('k-2', 'Beta Test')]));
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));

    expect(await screen.findByText('Beta Test')).toBeInTheDocument();
    expect(mock.listContacts.mock.calls.length).toBeGreaterThan(vorher);
    expect(mock.getSyncStatus.mock.calls.length).toBeGreaterThan(1);
  });

  it('lädt die Liste nach einem gescheiterten Lauf NICHT neu', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(
      lauf({ succeeded: false, error_class: 'BridgeProcessError', retryable: true }));
    await seiteRendern();
    const vorher = mock.listContacts.mock.calls.length;

    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    const ergebnis = await screen.findByTestId('sync-ergebnis');
    expect(ergebnis).toHaveTextContent(/fehlgeschlagen/);
    expect(ergebnis).toHaveTextContent(/BridgeProcessError/);
    expect(mock.listContacts.mock.calls.length).toBe(vorher);
  });

  it('behandelt einen leeren Lauf als Erfolg', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(
      lauf({ mode: 'delta', imported: 0, read: 0, unchanged: 0 }));
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    const ergebnis = await screen.findByTestId('sync-ergebnis');
    expect(ergebnis).toHaveTextContent(/Änderungsabgleich abgeschlossen/);
    expect(ergebnis).not.toHaveTextContent(/fehlgeschlagen/);
  });

  it('kündigt einen nötigen Vollabgleich an', async () => {
    const u = nutzer();
    mock.runSync.mockResolvedValue(lauf({ requires_full_diff: true }));
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    expect(await screen.findByText(/Vollabgleich nötig/i)).toBeInTheDocument();
  });

  it('sperrt den Knopf während des Laufs gegen Doppelklicks', async () => {
    const u = nutzer();
    let loesen: (v: unknown) => void = () => {};
    mock.runSync.mockReturnValue(new Promise((r) => { loesen = r; }));
    await seiteRendern();

    const knopf = screen.getByRole('button', { name: /synchronisieren/i });
    await u.click(knopf);
    await waitFor(() => expect(knopf).toBeDisabled());
    await u.click(knopf);
    await u.click(knopf);
    expect(mock.runSync).toHaveBeenCalledTimes(1);
    loesen(lauf());
  });

  it('zeigt einen Konflikt bei parallelem Lauf sichtbar an', async () => {
    const u = nutzer();
    mock.runSync.mockRejectedValue(
      new ContactsApiError(409, 'conflict', 'Es laeuft bereits ein Lauf', true));
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    expect(await screen.findByText(/laeuft bereits ein Lauf/)).toBeInTheDocument();
  });
});

// ═══ Freigaben ══════════════════════════════════════════════════════════════
const freigabe = (extra = {}) => ({
  approval_id: 'a-1', mutation_id: 'm-1', command: 'update',
  state: 'awaiting_approval', initiation_context: 'user_direct',
  actor: 'lukas', correlation_id: 'c-1',
  requested_at: '2026-07-29T09:00:00+00:00',
  expires_at: '2026-07-29T10:00:00+00:00', decided_at: null,
  decision_actor: null, preview_digest: 'abc', is_expired: false, ...extra,
});

async function freigabetafel(u: ReturnType<typeof nutzer>, approvals: unknown[]) {
  mock.listApprovals.mockResolvedValue(approvals);
  render(<ContactsPage />);
  await screen.findByText('Alpha Test');
  await u.click(screen.getByRole('tab', { name: 'Freigaben' }));
}

describe('Freigabetafel', () => {
  it('gibt frei', async () => {
    const u = nutzer();
    mock.approveMutation.mockResolvedValue(freigabe({ state: 'granted' }));
    await freigabetafel(u, [freigabe()]);
    await u.click(await screen.findByRole('button', { name: /^Freigeben$/i }));
    await waitFor(() => expect(mock.approveMutation).toHaveBeenCalledWith(
      'm-1', expect.any(String)));
  });

  it('lehnt ab', async () => {
    const u = nutzer();
    mock.rejectMutation.mockResolvedValue(freigabe({ state: 'rejected' }));
    await freigabetafel(u, [freigabe()]);
    await u.click(await screen.findByRole('button', { name: /^Ablehnen$/i }));
    await waitFor(() => expect(mock.rejectMutation).toHaveBeenCalled());
  });

  it('bricht ab', async () => {
    const u = nutzer();
    mock.cancelMutation.mockResolvedValue(freigabe({ state: 'cancelled' }));
    await freigabetafel(u, [freigabe()]);
    await u.click(await screen.findByRole('button', { name: /^Abbrechen$/i }));
    await waitFor(() => expect(mock.cancelMutation).toHaveBeenCalled());
  });

  it('markiert eine abgelaufene Freigabe ausdrücklich als abgelaufen', async () => {
    const u = nutzer();
    mock.expireMutation.mockResolvedValue(freigabe({ state: 'expired' }));
    await freigabetafel(u, [freigabe({ is_expired: true })]);
    const knopf = await screen.findByRole('button', { name: /Als abgelaufen markieren/i });
    await u.click(knopf);
    await waitFor(() => expect(mock.expireMutation).toHaveBeenCalledWith('m-1'));
  });

  it('bietet bei abgelaufener Freigabe keine Freigabe mehr an', async () => {
    const u = nutzer();
    await freigabetafel(u, [freigabe({ is_expired: true })]);
    await screen.findByRole('button', { name: /Als abgelaufen markieren/i });
    expect(screen.queryByRole('button', { name: /^Freigeben$/i })).toBeNull();
  });

  it('zeigt einen Konflikt bei zweiter Entscheidung an', async () => {
    const u = nutzer();
    mock.approveMutation.mockRejectedValue(
      new ContactsApiError(409, 'conflict', 'Bereits entschieden'));
    await freigabetafel(u, [freigabe()]);
    await u.click(await screen.findByRole('button', { name: /^Freigeben$/i }));
    expect(await screen.findByText(/Bereits entschieden/)).toBeInTheDocument();
  });

  it('zeigt einen erklärten Leerzustand ohne offene Freigaben', async () => {
    const u = nutzer();
    await freigabetafel(u, []);
    expect(await screen.findByText(/Keine offenen Freigaben/i)).toBeInTheDocument();
  });
});

// ═══ Vorgänge und Abgleich ══════════════════════════════════════════════════
const vorgang = (extra = {}) => ({
  mutation_id: 'm-1', command: 'update', state: 'outcome_unknown',
  outcome: null, initiation_context: 'user_direct', actor: 'lukas',
  correlation_id: 'c-1', provider_account_id: 'apple-local',
  target_contact_id: 'k-1', target_display_name: null,
  container_identifier: null, expected_revision: '1', attempt_count: 1,
  last_error_code: null, created_at: '2026-07-29T09:00:00+00:00',
  approved_at: null, completed_at: null, approval_id: 'a-1',
  approval_state: 'consumed', approval_expires_at: null,
  requires_reconcile: true, needs_manual_decision: false, ...extra,
});

describe('Vorgänge', () => {
  it('bietet bei unbekanntem Ausgang nur den Abgleich an, nie ein erneutes Senden', async () => {
    const u = nutzer();
    mock.listMutations.mockResolvedValue([vorgang()]);
    mock.getMutation.mockResolvedValue({
      ...vorgang(), changes: [], payload_digest: 'p', preview_digest: 'v',
    });
    render(<ContactsPage />);
    await screen.findByText('Alpha Test');
    await u.click(screen.getByRole('tab', { name: 'Vorgänge' }));
    await u.click(await screen.findByRole('button', { name: /Ausgang unbekannt/ }));

    expect(await screen.findByRole('button', { name: /Zustand abgleichen/i }))
      .toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /erneut senden/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /wiederholen/i })).toBeNull();
  });

  it('löst den Abgleich aus', async () => {
    const u = nutzer();
    mock.listMutations.mockResolvedValue([vorgang()]);
    mock.getMutation.mockResolvedValue({
      ...vorgang(), changes: [], payload_digest: 'p', preview_digest: 'v',
    });
    mock.reconcileMutation.mockResolvedValue({
      mutation_id: 'm-1', verdict: 'applied', state: 'succeeded',
      provider_identifier: null, detail: null,
    });
    render(<ContactsPage />);
    await screen.findByText('Alpha Test');
    await u.click(screen.getByRole('tab', { name: 'Vorgänge' }));
    await u.click(await screen.findByRole('button', { name: /Ausgang unbekannt/ }));
    await u.click(await screen.findByRole('button', { name: /Zustand abgleichen/i }));
    await waitFor(() => expect(mock.reconcileMutation).toHaveBeenCalledWith('m-1'));
  });
});

// ═══ Tastaturbedienung ══════════════════════════════════════════════════════
describe('Tastatur und Fokus', () => {
  async function dialogOeffnen(u: ReturnType<typeof nutzer>) {
    mock.getCapabilities.mockResolvedValue({ ...CAPS, update_supported: true,
                                             mutations_available: true });
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    const ausloeser = await screen.findByRole('button', { name: /^Ändern$/i });
    await u.click(ausloeser);
    return { dialog: await screen.findByRole('dialog'), ausloeser };
  }

  it('setzt den Fokus beim Öffnen in den Dialog', async () => {
    const u = nutzer();
    const { dialog } = await dialogOeffnen(u);
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it('schliesst mit Escape', async () => {
    const u = nutzer();
    await dialogOeffnen(u);
    await u.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('gibt den Fokus an das auslösende Element zurück', async () => {
    const u = nutzer();
    const { ausloeser } = await dialogOeffnen(u);
    await u.keyboard('{Escape}');
    await waitFor(() => expect(document.activeElement).toBe(ausloeser));
  });

  it('hält den Fokus mit Tab im Dialog', async () => {
    const u = nutzer();
    const { dialog } = await dialogOeffnen(u);
    for (let i = 0; i < 12; i += 1) {
      await u.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('hält den Fokus auch mit Shift+Tab im Dialog', async () => {
    const u = nutzer();
    const { dialog } = await dialogOeffnen(u);
    for (let i = 0; i < 12; i += 1) {
      await u.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('erlaubt die Bedienung der Übersicht per Tastatur', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.tab();
    expect(document.activeElement).not.toBe(document.body);
  });
});

// ═══ Keine direkten Provideraufrufe ═════════════════════════════════════════
describe('Grenzen', () => {
  it('spricht ausschliesslich über den API-Client', async () => {
    // Ein direkter `fetch` würde hier auffallen: er ist nicht gestellt.
    const direkt = vi.fn();
    vi.stubGlobal('fetch', direkt);
    const u = nutzer();
    mock.runSync.mockResolvedValue(lauf());
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /synchronisieren/i }));
    await screen.findByTestId('sync-ergebnis');
    expect(direkt).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('legt keine Roh-Identifier im sichtbaren Zustand ab', async () => {
    await seiteRendern();
    const text = document.body.textContent ?? '';
    expect(text).not.toContain('raw-1');
    expect(text).not.toContain('apple-local');
  });
});

// ═══ Regression: Fehlerdarstellung und geschlossene Mutationen ══════════════
//
// Beide Befunde stammen aus dem gescheiterten arm64-Livetest:
//   1. Die Oberfläche zeigte wörtlich „BridgeOperationError" — einen
//      Ausnahmeklassennamen, der dem Nutzer nichts sagt.
//   2. „Kontakt anlegen" war klickbar, obwohl produktive Provider-Mutationen
//      geschlossen sind und der Sidecar `not_implemented` antwortet.
describe('Fehlerdarstellung', () => {
  it('zeigt den Satz des Servers, nicht den Ausnahmeklassennamen', async () => {
    mock.listContacts.mockRejectedValue(new ContactsApiError(
      503, 'unavailable',
      'Die Kontakte-Bruecke liess sich nicht starten.', true,
      'bridge_start_failed:BridgeOperationError'));
    render(<ContactsPage />);
    const alarm = await screen.findByRole('alert');
    expect(alarm).toHaveTextContent(/liess sich nicht starten/);
    // Der Klassenname darf nur in der technischen Kennung stehen …
    const kennung = within(alarm).getByTestId('fehler-kennung');
    expect(kennung).toHaveTextContent(/bridge_start_failed/);
    // … und nie als die eigentliche Aussage.
    expect(alarm.querySelector('.font-medium')?.textContent)
      .not.toMatch(/BridgeOperationError/);
  });

  it('sagt, ob ein zweiter Versuch etwas bringt', async () => {
    mock.listContacts.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Brücke weg.', true, 'bridge_not_found'));
    render(<ContactsPage />);
    expect(await screen.findByText(/erneuter Versuch kann helfen/i))
      .toBeInTheDocument();
  });

  it('sagt auch, wenn ein zweiter Versuch nichts bringt', async () => {
    mock.listContacts.mockRejectedValue(new ContactsApiError(
      403, 'forbidden', 'Keine Berechtigung.', false, 'not_authorized:denied'));
    render(<ContactsPage />);
    expect(await screen.findByText(/ändert daran nichts/i)).toBeInTheDocument();
  });

  it('zeigt Kategorie und technische Kennung, aber keinen Pfad', async () => {
    mock.listContacts.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Brücke nicht gefunden.', true, 'bridge_not_found'));
    render(<ContactsPage />);
    const kennung = await screen.findByTestId('fehler-kennung');
    expect(kennung).toHaveTextContent('unavailable');
    expect(kennung).toHaveTextContent('bridge_not_found');
    expect(kennung.textContent).not.toMatch(/\//);
  });

  it('bleibt auch ohne Serverantwort verständlich', async () => {
    mock.listContacts.mockRejectedValue(new TypeError('Failed to fetch'));
    render(<ContactsPage />);
    expect(await screen.findByText(/Server war nicht erreichbar/i))
      .toBeInTheDocument();
  });

  it('nennt beim Brückenausfall den Grund und die Kennung', async () => {
    mock.getAuthorization.mockResolvedValue({
      status: 'unknown', can_request: false, bridge_available: false,
      reason: 'Die Kontakte-Bruecke wurde nicht gefunden.',
      technical_code: 'bridge_not_found',
    });
    await seiteRendern();
    expect(screen.getByText(/wurde nicht gefunden/)).toBeInTheDocument();
    expect(screen.getByTestId('auth-kennung')).toHaveTextContent('bridge_not_found');
  });
});

describe('Geschlossene Provider-Mutationen', () => {
  it('bietet „Kontakt anlegen" nicht an, solange Mutationen zu sind', async () => {
    await seiteRendern();
    expect(screen.queryByRole('button', { name: /Kontakt anlegen/i })).toBeNull();
  });

  it('bietet es an, sobald der Server die Fähigkeit meldet', async () => {
    mock.getCapabilities.mockResolvedValue({
      ...CAPS, create_supported: true, mutations_available: true,
    });
    await seiteRendern();
    expect(await screen.findByRole('button', { name: /Kontakt anlegen/i }))
      .toBeInTheDocument();
  });

  it('bietet weder Ändern noch Löschen an', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    await screen.findByRole('button', { name: /Zurück/i });
    expect(screen.queryByRole('button', { name: /^Ändern$/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Löschen$/i })).toBeNull();
  });

  it('erklärt, warum nicht — statt nur nichts anzuzeigen', async () => {
    const u = nutzer();
    await seiteRendern();
    await u.click(screen.getByRole('button', { name: /Alpha Test/ }));
    const hinweis = await screen.findByTestId('mutationen-gesperrt');
    expect(hinweis).toHaveTextContent(/liest Kontakte ausschliesslich/i);
  });

  it('bleibt fail-closed, wenn die Fähigkeiten unbekannt sind', async () => {
    // Der Capability-Abruf scheitert: dann gilt „nicht verfügbar", nicht
    // „vermutlich schon".
    mock.getCapabilities.mockRejectedValue(new Error('weg'));
    await seiteRendern();
    expect(screen.queryByRole('button', { name: /Kontakt anlegen/i })).toBeNull();
  });
});

// ═══ Regression: Apple-Fehlercode bleibt sichtbar ══════════════════════════
describe('Berechtigungsfehler', () => {
  async function notDetermined() {
    mock.getAuthorization.mockResolvedValue({
      status: 'notDetermined', can_request: true, bridge_available: true,
      reason: '', technical_code: '',
    });
    await seiteRendern();
  }

  it('zeigt Apple-Domain und Fehlercode statt eines Klassennamens', async () => {
    const u = nutzer();
    await notDetermined();
    mock.requestAuthorization.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Der Berechtigungsdialog konnte nicht angezeigt werden.',
      true, 'authorization_request:tcc_request_rejected:CNErrorDomain/100'));

    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    const kennung = await screen.findByTestId('fehler-kennung');
    expect(kennung).toHaveTextContent('CNErrorDomain/100');
    expect(kennung).toHaveTextContent('tcc_request_rejected');
    expect(kennung.textContent).not.toMatch(/BridgeOperationError/);
  });

  it('erklärt, wenn der Dialog nur aus der App kommen kann', async () => {
    const u = nutzer();
    await notDetermined();
    mock.requestAuthorization.mockRejectedValue(new ContactsApiError(
      503, 'unavailable',
      'Der Berechtigungsdialog kann nur aus der Anwendung selbst angefordert werden.',
      true, 'tcc_prompt_unavailable:handled_by_app'));

    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    expect(await screen.findByText(/nur aus der Anwendung selbst/i))
      .toBeInTheDocument();
    expect(screen.getByTestId('fehler-kennung'))
      .toHaveTextContent('handled_by_app');
  });

  it('wiederholt nach einem Fehlschlag nichts von selbst', async () => {
    const u = nutzer();
    await notDetermined();
    mock.requestAuthorization.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Abgelehnt.', true,
      'authorization_request:tcc_request_rejected:CNErrorDomain/100'));

    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    await screen.findByTestId('fehler-kennung');
    // Kein Timer, kein zweiter Aufruf.
    await new Promise((r) => { setTimeout(r, 120); });
    expect(mock.requestAuthorization).toHaveBeenCalledTimes(1);
  });

  it('löst durch erneutes Laden keinen zweiten Dialog aus', async () => {
    const u = nutzer();
    await notDetermined();
    mock.requestAuthorization.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Abgelehnt.', true, 'x:y'));
    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    await screen.findByTestId('fehler-kennung');

    // „Erneut laden" liest nur den Status — es fragt nichts an.
    await u.click(screen.getByRole('button', { name: /Erneut laden/i }));
    await waitFor(() => expect(mock.getAuthorization.mock.calls.length)
      .toBeGreaterThan(1));
    expect(mock.requestAuthorization).toHaveBeenCalledTimes(1);
  });

  it('zeigt nie einen Dateipfad an', async () => {
    const u = nutzer();
    await notDetermined();
    mock.requestAuthorization.mockRejectedValue(new ContactsApiError(
      503, 'unavailable', 'Der Dialog kann nur aus der Anwendung kommen.',
      true, 'tcc_prompt_unavailable:handled_by_app'));
    await u.click(screen.getByRole('button', { name: /erlauben/i }));
    await screen.findByTestId('fehler-kennung');
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/\/Users\//);
    expect(text).not.toMatch(/\.app/);
  });
});

// ═══ Ablageort der Neuanlage ════════════════════════════════════════════════
//
// Am 2026-08-01 musste ein Create-Livetest abgebrochen werden: beide
// Ablageorte standen öffentlich auf `unknown`, und die Auswahl des lokalen
// war damit nicht mehr belegbar — nur noch ratbar. Diese Tests halten fest,
// dass die Art das Auswahlmerkmal ist, und sonst nichts.
describe('Ablageort im Anlagedialog', () => {
  const MIT_CREATE = { ...CAPS, create_supported: true, mutations_available: true };

  const ort = (ref: string, art: string) => ({
    container_ref: ref, account_ref: 'A-9f2c11',
    provider_type: 'apple_contacts', container_type: art,
    last_successful_run_at: '2026-07-31T09:00:00+00:00',
  });

  async function dialogOeffnen(orte: unknown[]) {
    mock.getCapabilities.mockResolvedValue(MIT_CREATE);
    mock.listContainers.mockResolvedValue(orte);
    const u = nutzer();
    await seiteRendern();
    await u.click(await screen.findByRole('button', { name: /Kontakt anlegen/i }));
    return { u, feld: await screen.findByTestId('anlage-ablageort') };
  }

  it('benennt den lokalen Ablageort im Klartext', async () => {
    const { feld } = await dialogOeffnen([ort('C-1b3d99', 'local')]);
    expect(within(feld).getByText(/Lokal · Auf meinem Mac/)).toBeInTheDocument();
  });

  it('stellt einen unbekannten Ablageort nie als lokal dar', async () => {
    const { feld } = await dialogOeffnen([ort('C-4b8df1', 'unknown')]);
    expect(within(feld).queryByText(/Auf meinem Mac/)).toBeNull();
    expect(within(feld).getByText(/Art noch nicht bekannt/)).toBeInTheDocument();
    expect(screen.getByText(/Art noch nicht erhoben/)).toBeInTheDocument();
  });

  it('wählt einen unbekannten Ablageort auch als einzigen nicht vor', async () => {
    const { feld } = await dialogOeffnen([ort('C-4b8df1', 'unknown')]);
    expect((feld as HTMLSelectElement).value).toBe('');
  });

  it('unterscheidet die Ablageorte an der Art, nicht an der Reihenfolge', async () => {
    // Der lokale steht bewusst hinten: die Anzeige darf ihn trotzdem als
    // solchen ausweisen, und der kontogebundene darf es nie.
    const { feld } = await dialogOeffnen([
      ort('C-4b8df1', 'cardDAV'), ort('C-1b3d99', 'local'),
    ]);
    const lokal = within(feld).getByText(/Lokal · Auf meinem Mac/);
    expect(lokal).toHaveValue('C-1b3d99');
    expect(within(feld).getByText(/CardDAV \/ iCloud/)).toHaveValue('C-4b8df1');
    // Nichts ist vorausgewählt, solange es mehr als einen gibt.
    expect((feld as HTMLSelectElement).value).toBe('');
  });

  it('zeigt weder rohe Container- noch Kontokennungen', async () => {
    await dialogOeffnen([ort('C-1b3d99', 'local'), ort('C-4b8df1', 'cardDAV')]);
    const text = document.body.textContent ?? '';
    expect(text).not.toMatch(/ABAccount/);
    expect(text).not.toMatch(/[0-9A-F]{8}-[0-9A-F]{4}-/i);
  });
});

// ═══ App-Prozess-Save-Spike (isolierter Branch) ═════════════════════════════
describe('AppSave-Spike-Sektion', () => {
  const previewFixture = {
    given_name: 'ZZZ-JarvisTest-AppSave', contact_type: 'person',
    container_type_label: 'Lokal · Auf meinem Mac',
    confirmation_phrase: 'APP-SAVE-SPIKE JETZT AUSFÜHREN',
    preview_digest: 'd'.repeat(64), nonce: 'n'.repeat(32),
    notice: 'Es wird genau ein Testkontakt angelegt. '
      + 'Kein automatischer Wiederholungsversuch.',
  };

  it('bleibt ohne Freigabe vollständig unsichtbar', async () => {
    mock.appSaveSpikeStatus.mockResolvedValue({
      enabled: false, phase: 'not_started',
    });
    await seiteRendern();
    expect(screen.queryByTestId('app-save-spike')).toBeNull();
  });

  it('führt genau einmal aus und sperrt den Knopf dauerhaft', async () => {
    mock.appSaveSpikeStatus.mockResolvedValue({
      enabled: true, phase: 'not_started',
    });
    mock.appSaveSpikePrepare.mockResolvedValue(previewFixture);
    mock.appSaveSpikeExecute.mockResolvedValue({
      outcome: 'applied', save_attempts: 1, applied: true,
      outcome_unknown: false, provider_identifier_present: true,
      provider_identifier_digest: 'a'.repeat(64), readback_succeeded: true,
      given_name_matched: true, container_type: 'local', error_domain: null,
      error_code: null, exception_name: null, reason_present: false,
      reason_digest: null, diagnostics_artifact_written: false,
    });
    const u = nutzer();
    await seiteRendern();
    await u.click(await screen.findByTestId('spike-vorbereiten'));
    expect(mock.appSaveSpikePrepare).toHaveBeenCalledTimes(1);
    // Ohne die wörtliche Phrase bleibt Ausführen gesperrt.
    const knopf = await screen.findByTestId('spike-ausfuehren');
    expect(knopf).toBeDisabled();
    await u.type(screen.getByTestId('spike-phrase'),
                 previewFixture.confirmation_phrase);
    expect(knopf).toBeEnabled();
    await u.click(knopf);
    await screen.findByTestId('spike-ergebnis');
    expect(mock.appSaveSpikeExecute).toHaveBeenCalledTimes(1);
    expect(mock.appSaveSpikeExecute).toHaveBeenCalledWith(
      previewFixture.confirmation_phrase, previewFixture.nonce,
      previewFixture.preview_digest);
    // Dauerhaft gesperrt — ein zweiter Klick löst nichts aus.
    expect(knopf).toBeDisabled();
    await u.click(knopf);
    expect(mock.appSaveSpikeExecute).toHaveBeenCalledTimes(1);
  });

  it('zeigt im Ergebnis nur Digests, nie eine rohe Kennung', async () => {
    mock.appSaveSpikeStatus.mockResolvedValue({
      enabled: true, phase: 'not_started',
    });
    mock.appSaveSpikePrepare.mockResolvedValue(previewFixture);
    mock.appSaveSpikeExecute.mockResolvedValue({
      outcome: 'caught_exception', save_attempts: 1, applied: false,
      outcome_unknown: true, provider_identifier_present: false,
      provider_identifier_digest: null, readback_succeeded: false,
      given_name_matched: false, container_type: null, error_domain: null,
      error_code: null, exception_name: 'NSInternalInconsistencyException',
      reason_present: true, reason_digest: 'b'.repeat(64),
      diagnostics_artifact_written: true,
    });
    const u = nutzer();
    await seiteRendern();
    await u.click(await screen.findByTestId('spike-vorbereiten'));
    await u.type(screen.getByTestId('spike-phrase'),
                 previewFixture.confirmation_phrase);
    await u.click(screen.getByTestId('spike-ausfuehren'));
    const text = (await screen.findByTestId('spike-ergebnis')).textContent ?? '';
    expect(text).toContain('NSInternalInconsistencyException');
    expect(text).not.toMatch(/ABPerson|ABAccount/);
    expect(text).not.toMatch(/reason":\s*"(?!null)/);
  });
});

// G · Der Ausführungsschritt der Command Bar gibt nicht mehr selbst frei.
//
// Vorher rief `fuehreAus` für Kontakte `approveMutation(id, ENTSCHEIDER)` mit
// einem hartkodierten `'lukas'` — der Execute-Pfad erteilte sich die Freigabe,
// die er gleich verbrauchte. Damit war die Trennung von Vorbereiten und
// Ausführen aufgehoben, und ein vom Produktcode gewählter String stand an der
// Stelle einer Eigentümerhandlung.
//
// Geprüft wird gegen den **echten** Adapter, nicht gegen einen Stub-Port: Die
// vorhandene Core-Suite arbeitet mit einem Zählport und hätte diese Änderung
// nicht bemerkt.

import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  // Bewusst **vorhanden**: Der alte Adapter soll alles bekommen, was er zum
  // Freigeben braucht. Ein Mock ohne diese Funktion liesse ihn an einem
  // `undefined` scheitern, und die Tests bestuenden aus dem falschen Grund.
  approveMutation: vi.fn(async () => ({ state: 'granted' })),
  getMutation: vi.fn(),
  executeMutation: vi.fn(),
  getContact: vi.fn(),
  listContacts: vi.fn(),
  listContainers: vi.fn(),
  prepareCreate: vi.fn(),
  prepareDelete: vi.fn(),
  prepareUpdate: vi.fn(),
}));

vi.mock('../personal/contacts/api', () => api);
vi.mock('../personal/calendar/api', () => ({
  ladeKalender: vi.fn(), ladeTermine: vi.fn(),
}));
vi.mock('../personal/calendar/mutationsApi', () => ({
  beanspruche: vi.fn(), bereiteUpdateVor: vi.fn(), bereiteVor: vi.fn(),
  fuehreAus: vi.fn(), gibFrei: vi.fn(), schliesseAb: vi.fn(),
}));

const { produktiverWritePort } = await import('./writeAdapter');
const { SchreibFehler } = await import('./writePort');

const vorbereitet = {
  operation: 'kontakt_aendern' as const,
  mutationId: 'm-1',
  kanal: 'kontakte' as const,
  gebundenerZustand: 'digest-1',
  ziel: { id: 'k-1', bezeichnung: 'Fixture Eins', container: 'C-1' },
  vorschau: [],
};

const vorgang = (over: Record<string, unknown> = {}) => ({
  mutation_id: 'm-1', command: 'update', state: 'approved',
  approval_state: 'granted', ...over,
});

describe('Der Execute-Pfad erteilt keine Freigabe', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.executeMutation.mockResolvedValue({
      outcome: 'succeeded', state: 'succeeded', contact_id: 'k-1',
    });
    api.getContact.mockResolvedValue({
      id: 'k-1', display_name: 'Fixture Eins', organization_name: null,
      job_title: null, emails: [], phones: [],
    });
  });

  it('führt einen freigegebenen Vorgang aus, ohne vorher freizugeben', async () => {
    api.getMutation.mockResolvedValue(vorgang());
    await produktiverWritePort().fuehreAus(vorbereitet);
    expect(api.executeMutation).toHaveBeenCalledWith('m-1');
    // Der eigentliche Befund: Freigeben ist kein Teil des Ausführens mehr.
    expect(api.approveMutation).not.toHaveBeenCalled();
  });

  it('verweigert einen wartenden Vorgang und erzeugt keine Freigabe', async () => {
    api.getMutation.mockResolvedValue(
      vorgang({ state: 'awaiting_approval', approval_state: 'awaiting_approval' }));

    await expect(produktiverWritePort().fuehreAus(vorbereitet))
      .rejects.toMatchObject({ art: 'freigabe_fehlt', phase: 'ausfuehren' });
    expect(api.executeMutation).not.toHaveBeenCalled();
    expect(api.approveMutation).not.toHaveBeenCalled();
  });

  it('verweigert eine abgelaufene Freigabe', async () => {
    // `approval_state` ist der **wirksame** Zustand: Eine erteilte, aber
    // abgelaufene Freigabe liest sich als `expired`.
    api.getMutation.mockResolvedValue(
      vorgang({ state: 'approved', approval_state: 'expired' }));

    await expect(produktiverWritePort().fuehreAus(vorbereitet))
      .rejects.toBeInstanceOf(SchreibFehler);
    expect(api.executeMutation).not.toHaveBeenCalled();
    expect(api.approveMutation).not.toHaveBeenCalled();
  });

  it('verweigert einen bereits verbrauchten Vorgang', async () => {
    api.getMutation.mockResolvedValue(
      vorgang({ state: 'succeeded', approval_state: 'consumed' }));

    await expect(produktiverWritePort().fuehreAus(vorbereitet))
      .rejects.toBeInstanceOf(SchreibFehler);
    expect(api.executeMutation).not.toHaveBeenCalled();
    expect(api.approveMutation).not.toHaveBeenCalled();
  });

  it('liest den Zustand frisch statt ihn aus der Vorbereitung zu erinnern', async () => {
    // Zwischen Prepare und Execute kann die Freigabe erteilt, abgelaufen oder
    // verbraucht worden sein — die Vorbereitung weiss davon nichts.
    api.getMutation.mockResolvedValue(vorgang());
    await produktiverWritePort().fuehreAus(vorbereitet);
    expect(api.getMutation).toHaveBeenCalledWith('m-1');
    expect(api.approveMutation).not.toHaveBeenCalled();
  });
});

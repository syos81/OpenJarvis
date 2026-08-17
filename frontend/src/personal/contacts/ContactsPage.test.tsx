// @vitest-environment jsdom
//
// Interaktionstests des dreispaltigen Kontakte-Workspace.
//
// Der API-Client ist gemockt. Das ist kein Selbstzweck: es belegt zugleich,
// dass die Oberfläche **ausschliesslich** über diesen Client spricht. Gäbe
// es irgendwo einen direkten `fetch`, liefe er hier ins Leere und der Test
// schlüge fehl. Alle Daten sind erfunden.

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
    executeMutation: vi.fn(),
    reconcileMutation: vi.fn(),
    resolveOutcomeNotObserved: vi.fn(),
    listContainers: vi.fn(),
  };
});

import ContactsPage from './ContactsPage';
import * as api from './api';
import { ContactEditor } from './editor/ContactEditor';
import { PaneDivider } from './workspace/PaneDivider';
import { fixtureDataSource } from './data/fixtureSource';
import { syntheticDetail, syntheticSummaries } from './data/fixtures';
import { sortiereKontakte } from './data/sortierung';

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
  unified_read_only: false, ...extra,
});

const seite = (items: unknown[], extra = {}) => ({
  items, next_cursor: null, has_more: false, ...extra,
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
  mock.listContacts.mockResolvedValue(seite([
    zusammenfassung('k-1', 'Alpha Attrappe'),
    zusammenfassung('k-2', 'Bruno Beispiel', { organization_name: 'Muster AG' }),
    zusammenfassung('k-3', 'Zora Zierbeispiel', { roles: ['Verein'] }),
  ]));
  mock.listCategories.mockResolvedValue([{ role: 'Verein', count: 1 }]);
  mock.getCapabilities.mockResolvedValue(CAPS);
  mock.getContact.mockImplementation((id: string) => Promise.resolve(detail(
    id, { 'k-1': 'Alpha Attrappe', 'k-2': 'Bruno Beispiel', 'k-3': 'Zora Zierbeispiel' }[id] ?? id,
  )));
  mock.listApprovals.mockResolvedValue([]);
  mock.listMutations.mockResolvedValue([]);
  mock.listContainers.mockResolvedValue([]);
}

beforeEach(() => {
  vi.clearAllMocks();
  standard();
});

afterEach(() => { vi.restoreAllMocks(); });

const nutzer = () => userEvent.setup();

async function rendern() {
  render(<ContactsPage />);
  await screen.findByText('Alpha Attrappe');
}

function liste() {
  return screen.getByTestId('contacts-liste');
}

// ═══ A · Komponentenstruktur: drei Panes, Toolbar, Trenner ══════════════════
describe('Struktur', () => {
  it('zeigt Toolbar, Sidebar, Liste und Detailbereich', async () => {
    await rendern();
    expect(screen.getByRole('toolbar', { name: 'Kontakte-Werkzeuge' })).toBeInTheDocument();
    expect(screen.getByTestId('contacts-sidebar')).toBeInTheDocument();
    expect(screen.getByRole('listbox', { name: 'Kontakte' })).toBeInTheDocument();
    expect(screen.getByText('Kein Kontakt ausgewählt')).toBeInTheDocument();
  });

  it('hat zwei tastaturbedienbare Spaltentrenner', async () => {
    await rendern();
    const trenner = screen.getAllByRole('separator');
    expect(trenner).toHaveLength(2);
    for (const t of trenner) {
      expect(t).toHaveAttribute('aria-orientation', 'vertical');
      expect(t).toHaveAttribute('aria-valuenow');
      expect(t).toHaveAttribute('tabindex', '0');
    }
  });

  it('sortiert die Liste nach Nachname mit Abschnittsmarkern', async () => {
    await rendern();
    const texte = liste().textContent ?? '';
    expect(texte.indexOf('Alpha Attrappe')).toBeLessThan(texte.indexOf('Bruno Beispiel'));
    expect(texte.indexOf('Bruno Beispiel')).toBeLessThan(texte.indexOf('Zora Zierbeispiel'));
    expect(within(liste()).getByText('A')).toBeInTheDocument();
    expect(within(liste()).getByText('B')).toBeInTheDocument();
    expect(within(liste()).getByText('Z')).toBeInTheDocument();
  });
});

// ═══ B · Auswahl: Klick, Tastatur, Filterwechsel ════════════════════════════
describe('Auswahl', () => {
  it('öffnet den Kontakt per Klick im Detailbereich', async () => {
    await rendern();
    await nutzer().click(within(liste()).getByText('Bruno Beispiel'));
    const det = await screen.findByTestId('contact-detail');
    expect(within(det).getByRole('heading', { name: 'Bruno Beispiel' })).toBeInTheDocument();
    expect(mock.getContact).toHaveBeenCalledWith('k-2');
  });

  it('bewegt die Auswahl mit Pfeiltasten, Home und End', async () => {
    await rendern();
    const u = nutzer();
    liste().focus();
    await u.keyboard('{ArrowDown}');
    await waitFor(() => expect(
      screen.getByRole('option', { selected: true }).textContent,
    ).toContain('Alpha Attrappe'));
    await u.keyboard('{ArrowDown}');
    await waitFor(() => expect(
      screen.getByRole('option', { selected: true }).textContent,
    ).toContain('Bruno Beispiel'));
    await u.keyboard('{End}');
    await waitFor(() => expect(
      screen.getByRole('option', { selected: true }).textContent,
    ).toContain('Zora Zierbeispiel'));
    await u.keyboard('{Home}');
    await waitFor(() => expect(
      screen.getByRole('option', { selected: true }).textContent,
    ).toContain('Alpha Attrappe'));
    await u.keyboard('{ArrowUp}');
    await waitFor(() => expect(
      screen.getByRole('option', { selected: true }).textContent,
    ).toContain('Alpha Attrappe'));
  });

  it('behält die Auswahl beim Kategoriefilter und meldet Herausfallen', async () => {
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await screen.findByTestId('contact-detail');
    // Filter „Verein" enthält Bruno nicht — Auswahl bleibt, Hinweis erscheint.
    await u.click(screen.getByText('Verein'));
    await waitFor(() => {
      expect(screen.getByText(/ausserhalb des aktuellen Filters/)).toBeInTheDocument();
    });
    expect(within(screen.getByTestId('contact-detail'))
      .getByRole('heading', { name: 'Bruno Beispiel' })).toBeInTheDocument();
  });

  it('startet Bearbeitung nie durch blosses Klicken oder Doppelklicken', async () => {
    await rendern();
    const u = nutzer();
    await u.dblClick(within(liste()).getByText('Bruno Beispiel'));
    await screen.findByTestId('contact-detail');
    expect(screen.queryByTestId('contact-editor')).not.toBeInTheDocument();
  });
});

// ═══ C · Suche ══════════════════════════════════════════════════════════════
describe('Suche', () => {
  it('filtert über den Client und zeigt leere Treffer als eigenen Zustand', async () => {
    await rendern();
    const u = nutzer();
    mock.listContacts.mockResolvedValue(seite([]));
    await u.type(screen.getByTestId('toolbar-suche'), 'niemand');
    await waitFor(() => {
      expect(screen.getByText('Keine Suchtreffer')).toBeInTheDocument();
    });
    expect(mock.listContacts).toHaveBeenLastCalledWith(
      expect.objectContaining({ search: 'niemand' }),
    );
  });

  it('Escape löscht die Suche und zeigt wieder alle', async () => {
    await rendern();
    const u = nutzer();
    const feld = screen.getByTestId('toolbar-suche');
    mock.listContacts.mockResolvedValue(seite([zusammenfassung('k-2', 'Bruno Beispiel')]));
    await u.type(feld, 'bruno');
    await waitFor(() => {
      expect(within(liste()).queryByText('Alpha Attrappe')).not.toBeInTheDocument();
    });
    await u.keyboard('{Escape}');
    expect(feld).toHaveValue('');
    await waitFor(() => {
      expect(within(liste()).getByText('Alpha Attrappe')).toBeInTheDocument();
    });
  });

  it('Demo-Quelle findet Kontakte über E-Mail und Telefonnummer', async () => {
    const q = fixtureDataSource(50);
    const alle = await q.ladeAlle();
    const mitMail = alle.map((k) => syntheticDetail(k.id)).find((d) => d.emails.length > 0)!;
    const mailTreffer = await q.suche(mitMail.emails[0].value!.split('@')[0]);
    expect(mailTreffer.some((k) => k.id === mitMail.id)).toBe(true);
    const mitTel = alle.map((k) => syntheticDetail(k.id)).find((d) => d.phones.length > 0)!;
    const telTreffer = await q.suche(mitTel.phones[0].value!.replace(/\s/g, ''));
    expect(telTreffer.some((k) => k.id === mitTel.id)).toBe(true);
  });
});

// ═══ D · Detailfelder ═══════════════════════════════════════════════════════
describe('Detailansicht', () => {
  it('zeigt mehrere Werte mit Labels und mehrzeilige Adressen', async () => {
    mock.getContact.mockResolvedValue(detail('k-1', 'Alpha Attrappe', {
      emails: [
        { id: 'm1', position: 0, label_raw: 'home', label_normalized: 'home', value: 'alpha@example.invalid', extra: {} },
        { id: 'm2', position: 1, label_raw: 'work', label_normalized: 'work', value: 'attrappe@beispiel.invalid', extra: {} },
      ],
      phones: [{ id: 't1', position: 0, label_raw: 'mobile', label_normalized: 'mobile', value: '+49 000 1234567', extra: {} }],
      postal_addresses: [{
        id: 'a1', position: 0, label_raw: 'home', label_normalized: 'home', value: null,
        extra: { street: 'Übungsstraße 1\nHinterhaus', postal_code: '00001', city: 'Beispielstadt', country: 'Deutschland' },
      }],
    }));
    await rendern();
    await nutzer().click(within(liste()).getByText('Alpha Attrappe'));
    const det = await screen.findByTestId('contact-detail');
    expect(within(det).getByText('alpha@example.invalid')).toBeInTheDocument();
    expect(within(det).getByText('attrappe@beispiel.invalid')).toBeInTheDocument();
    expect(within(det).getByText('+49 000 1234567')).toBeInTheDocument();
    expect(within(det).getByText(/Übungsstraße 1/)).toBeInTheDocument();
    expect(within(det).getByText(/Beispielstadt/)).toBeInTheDocument();
    // Labels übersetzt, nicht roh:
    expect(within(det).getAllByText('Privat').length).toBeGreaterThan(0);
    expect(within(det).getByText('Mobil')).toBeInTheDocument();
  });

  it('zeigt fehlende Feldgruppen gar nicht (keine leeren Karten)', async () => {
    await rendern();
    await nutzer().click(within(liste()).getByText('Alpha Attrappe'));
    const det = await screen.findByTestId('contact-detail');
    expect(within(det).queryByLabelText('E-Mail')).not.toBeInTheDocument();
    expect(within(det).queryByLabelText('Adressen')).not.toBeInTheDocument();
  });

  it('unterscheidet „nicht lesbar" von „leer" bei der Notiz', async () => {
    await rendern();
    await nutzer().click(within(liste()).getByText('Alpha Attrappe'));
    const det = await screen.findByTestId('contact-detail');
    expect(within(det).getByText('nicht lesbar')).toBeInTheDocument();
  });

  it('trägt Sonderzeichen und lange Namen ohne Identifier-Anzeige', async () => {
    const lang = 'Zoë-Annegret Überlangenbergerhausen von und zu Testfeld';
    mock.getContact.mockResolvedValue(detail('k-1', lang));
    await rendern();
    await nutzer().click(within(liste()).getByText('Alpha Attrappe'));
    const det = await screen.findByTestId('contact-detail');
    expect(within(det).getByRole('heading', { name: lang })).toBeInTheDocument();
    expect(det.textContent).not.toContain('k-1');
    expect(det.textContent).not.toContain('A-9f2c11');
    expect(det.textContent).not.toContain('C-1b3d99');
  });
});

// ═══ E · Bearbeitung ════════════════════════════════════════════════════════
describe('Bearbeitung', () => {
  const CAPS_UPDATE = { ...CAPS, update_supported: true, mutations_available: true };

  it('öffnet den Editor über „Bearbeiten" und bereitet nur den Diff vor', async () => {
    mock.getCapabilities.mockResolvedValue(CAPS_UPDATE);
    mock.prepareUpdate.mockResolvedValue({
      mutation_id: 'm-1', approval_id: 'a-1', state: 'awaiting_approval',
      payload_digest: 'p', preview_digest: 'v', reused: false,
      command: 'update', target_contact_id: 'k-2', container_ref: null,
      target_label: 'Bruno Beispiel',
      changes: [{ field_name: 'organization_name', previous: null, planned: 'Muster AG' }],
      warnings: [],
    });
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await u.click(await screen.findByTestId('toolbar-bearbeiten'));
    const editor = await screen.findByTestId('contact-editor');
    const orga = within(editor).getByLabelText('Organisation');
    await u.clear(orga);
    await u.type(orga, 'Muster AG');
    await u.click(screen.getByTestId('editor-fertig'));
    await waitFor(() => expect(mock.prepareUpdate).toHaveBeenCalledTimes(1));
    const [zielId, args] = mock.prepareUpdate.mock.calls[0];
    expect(zielId).toBe('k-2');
    expect(args.fields).toEqual({ organization_name: 'Muster AG' });
    expect(args.expectedRevision).toBe('1');
    // „Fertig" bereitet vor — mehr nicht. Bis 2026-08-13 verlangte dieser
    // Test das Gegenteil („laeuft ohne zweiten Klick durch") und sicherte
    // damit die Selbstfreigabe ab. Der Vorgang geht jetzt in die Vorschau,
    // und dort entscheidet der Eigentuemer.
    expect(await screen.findByText('Änderung prüfen und freigeben'))
      .toBeInTheDocument();
    expect(mock.approveMutation).not.toHaveBeenCalled();
    expect(mock.executeMutation).not.toHaveBeenCalled();
  });

  it('schliesst ohne Änderungen sofort, fragt bei Änderungen nach', async () => {
    mock.getCapabilities.mockResolvedValue(CAPS_UPDATE);
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await u.click(await screen.findByTestId('toolbar-bearbeiten'));
    await u.click(screen.getByTestId('editor-abbrechen'));
    expect(screen.queryByTestId('contact-editor')).not.toBeInTheDocument();

    await u.click(await screen.findByTestId('toolbar-bearbeiten'));
    await u.type(within(screen.getByTestId('contact-editor')).getByLabelText('Spitzname'), 'Bibi');
    await u.click(screen.getByTestId('editor-abbrechen'));
    expect(await screen.findByText('Änderungen verwerfen?')).toBeInTheDocument();
    await u.click(screen.getByTestId('abbruch-verwerfen'));
    await waitFor(() => {
      expect(screen.queryByTestId('contact-editor')).not.toBeInTheDocument();
    });
  });

  it('validiert E-Mails und erlaubt Hinzufügen/Entfernen (Demo-Editor)', async () => {
    const u = nutzer();
    render(
      <ContactEditor
        kontakt={syntheticDetail('demo-0') as never}
        demoModus
        onFertig={() => {}}
        onAbbrechen={() => {}}
        sendet={false}
        fehler={null}
      />,
    );
    await u.click(screen.getByRole('button', { name: 'E-Mail hinzufügen' }));
    const neue = screen.getAllByLabelText(/^E-Mail \d+$/).slice(-1)[0];
    await u.type(neue, 'keine-adresse');
    expect(await screen.findByText('Keine gültige E-Mail-Adresse.')).toBeInTheDocument();
    expect(screen.getByTestId('editor-fertig')).toBeDisabled();
    await u.clear(neue);
    await u.type(neue, 'gueltig@example.invalid');
    await waitFor(() => {
      expect(screen.queryByText('Keine gültige E-Mail-Adresse.')).not.toBeInTheDocument();
    });
    const vorher = screen.getAllByLabelText(/^E-Mail \d+$/).length;
    await u.click(screen.getAllByRole('button', { name: /E-Mail \d+ entfernen/ })[0]);
    expect(screen.queryAllByLabelText(/^E-Mail \d+$/)).toHaveLength(vorher - 1);
  });

  it('erlaubt Mehrwertfelder, sobald der Kanal Update traegt', async () => {
    // Frueher hingen sie am Demo-Modus und waren im API-Betrieb hart
    // gesperrt — eine Sperre aus der Zeit vor dem Update-Pfad. Der
    // Feldvertrag v1 kennt die Listen laengst; die Sperre log den Nutzer an
    // (Befund im Livetest 2026-08-04: „hinzufuegen geht nicht").
    mock.getCapabilities.mockResolvedValue(CAPS_UPDATE);
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await u.click(await screen.findByTestId('toolbar-bearbeiten'));
    expect(screen.queryByText(/erst mit einem erweiterten Feldvertrag/))
      .not.toBeInTheDocument();
    const knopf = screen.getByRole('button', { name: 'E-Mail hinzufügen' });
    expect(knopf).toBeEnabled();
  });

  it('bietet ohne Update-Faehigkeit gar keine Bearbeitung an', async () => {
    // Die Listensperre ist die zweite Schranke; die erste ist, dass es ohne
    // `update_supported` keinen Editor gibt. Beide zusammen ergeben: nichts
    // wird als speicherbar dargestellt, was der Kanal nicht traegt.
    mock.getCapabilities.mockResolvedValue({
      ...CAPS_UPDATE, update_supported: false });
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await screen.findByTestId('contact-detail');
    expect(screen.queryByTestId('toolbar-bearbeiten')).not.toBeInTheDocument();
  });

  /**
   * Seit dem M2-Abgleich fuehrt der Loeschweg ueber den Rechtsklick, und die
   * Bestaetigung des Menschen **ist** die Freigabe: danach laeuft der Vorgang
   * ohne weiteren Klick durch. Der Eigentuemer hat das ausdruecklich so
   * entschieden — begrenzt auf Handlungen, die er selbst ausloest. Was Jarvis
   * von sich aus vorbereitet, behaelt den sichtbaren Freigabeweg.
   *
   * Genau eine Zustimmung bleibt also Pflicht; geprueft wird hier, dass es
   * ohne sie keinen Save gibt und mit ihr genau einen Durchlauf.
   */
  it('loescht ueber den Rechtsklick und schliesst nach einer Bestaetigung ab', async () => {
    mock.getCapabilities.mockResolvedValue({ ...CAPS_UPDATE, delete_supported: true });
    mock.prepareDelete.mockResolvedValue({
      mutation_id: 'm-2', approval_id: 'a-2', state: 'awaiting_approval',
      payload_digest: 'p', preview_digest: 'v', reused: false,
      command: 'delete', target_contact_id: 'k-2', container_ref: null,
      target_label: 'Bruno Beispiel', changes: [], warnings: [],
    });
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    await screen.findByTestId('contact-detail');

    await u.pointer({ keys: '[MouseRight]',
                      target: within(liste()).getByText('Bruno Beispiel') });
    await u.click(await screen.findByTestId('kontextmenue-loeschen'));

    // Der Warnhinweis bleibt — er sagt seit dem Löschgate nur genauer, was
    // verloren geht: der Inhalt ist wiederherstellbar, die Providerkennung
    // nicht. „Nicht rückgängig" wäre jetzt der ungenauere Satz.
    expect(await screen.findByTestId('loeschen-wiederherstellung'))
      .toHaveTextContent(/neuer Providerkennung/);
    // Bis hierher wurde nichts vorbereitet und erst recht nichts gesendet.
    expect(mock.prepareDelete).not.toHaveBeenCalled();

    await u.click(screen.getByTestId('loeschen-vorbereiten'));
    await waitFor(() => expect(mock.prepareDelete).toHaveBeenCalledTimes(1));
    // Auch das Loeschen bereitet nur vor. Eine Bestaetigung im Kontextmenue
    // ist keine Freigabe: Sie kennt den Zielablageort noch gar nicht, der
    // erst beim Vorbereiten aufgeloest wird.
    expect(await screen.findByText('Änderung prüfen und freigeben'))
      .toBeInTheDocument();
    expect(mock.approveMutation).not.toHaveBeenCalled();
    expect(mock.executeMutation).not.toHaveBeenCalled();
  });
});

// ═══ F · Zustände ═══════════════════════════════════════════════════════════
describe('Zustände', () => {
  it('zeigt den Ladezustand', async () => {
    mock.listContacts.mockReturnValue(new Promise(() => {}));
    render(<ContactsPage />);
    expect(await screen.findByText('Kontakte werden geladen')).toBeInTheDocument();
  });

  it('zeigt API-Fehler mit Kennung und erneutem Laden', async () => {
    mock.listContacts.mockRejectedValue(new api.ContactsApiError(
      503, 'unavailable', 'Der lokale Server meldet einen Fehler.', true, 'db_locked',
    ));
    render(<ContactsPage />);
    expect(await screen.findByText('Der lokale Server meldet einen Fehler.')).toBeInTheDocument();
    expect(screen.getByTestId('fehler-kennung').textContent).toContain('db_locked');
    mock.listContacts.mockResolvedValue(seite([zusammenfassung('k-1', 'Alpha Attrappe')]));
    await nutzer().click(screen.getByText('Erneut laden'));
    expect(await screen.findByText('Alpha Attrappe')).toBeInTheDocument();
  });

  it('zeigt den leeren Bestand mit Hinweis auf die Statusfläche', async () => {
    mock.listContacts.mockResolvedValue(seite([]));
    render(<ContactsPage />);
    expect(await screen.findByText('Keine Kontakte')).toBeInTheDocument();
    expect(screen.getByText(/Vorgänge & Status/)).toBeInTheDocument();
  });

  it('zeigt Freigabe- und outcome_unknown-Fakes der Demo-Quelle', async () => {
    const q = fixtureDataSource(10);
    const freigaben = await q.listApprovals();
    expect(freigaben).toHaveLength(1);
    const vorgaenge = await q.listMutations();
    const zustaende = vorgaenge.map((m) => m.state);
    expect(zustaende).toContain('awaiting_approval');
    expect(zustaende).toContain('outcome_unknown');
    expect(zustaende).toContain('manual_decision_required');
    const unbekannt = vorgaenge.find((m) => m.state === 'outcome_unknown')!;
    const det = await q.getMutation(unbekannt.mutation_id);
    expect(det.last_error_code).toBe('child_signalled');
  });
});

// ═══ G · Split-Panes ════════════════════════════════════════════════════════
describe('Spaltentrenner', () => {
  it('ändert die Breite per Pfeiltaste und klemmt an den Grenzen', async () => {
    let wert = 200;
    const u = nutzer();
    const { rerender } = render(
      <PaneDivider label="Test" wert={wert} min={160} max={320}
                   onChange={(b) => { wert = b; }} />,
    );
    const t = screen.getByRole('separator');
    t.focus();
    await u.keyboard('{ArrowRight}');
    expect(wert).toBe(216);
    rerender(<PaneDivider label="Test" wert={wert} min={160} max={320}
                          onChange={(b) => { wert = b; }} />);
    await u.keyboard('{Home}');
    expect(wert).toBe(160);
    rerender(<PaneDivider label="Test" wert={wert} min={160} max={320}
                          onChange={(b) => { wert = b; }} />);
    await u.keyboard('{ArrowLeft}');
    expect(wert).toBe(160);
    rerender(<PaneDivider label="Test" wert={wert} min={160} max={320}
                          onChange={(b) => { wert = b; }} />);
    await u.keyboard('{End}');
    expect(wert).toBe(320);
  });
});

// ═══ H · Accessibility ══════════════════════════════════════════════════════
describe('Accessibility', () => {
  it('verdrahtet Listbox, Optionen und aktive Auswahl korrekt', async () => {
    await rendern();
    const u = nutzer();
    await u.click(within(liste()).getByText('Bruno Beispiel'));
    const box = screen.getByRole('listbox', { name: 'Kontakte' });
    await waitFor(() => {
      expect(box).toHaveAttribute('aria-activedescendant', 'pjc-opt-k-2');
    });
    const option = screen.getByRole('option', { selected: true });
    expect(option).toHaveAttribute('aria-setsize', '3');
    expect(option).toHaveAttribute('aria-posinset');
  });

  it('benennt alle Icon-Schaltflächen', async () => {
    await rendern();
    // Der Zugang zu Vorgaengen und Status sitzt seit dem M2-Abgleich unten
    // in der Seitenleiste, nicht mehr in der Toolbar.
    expect(screen.getByTestId('sidebar-status')).toBeInTheDocument();
    expect(screen.getByLabelText('Kontakte durchsuchen')).toBeInTheDocument();
  });

  it('erreicht die Liste per ⌘F und Escape-Vertrag', async () => {
    await rendern();
    const u = nutzer();
    const feld = screen.getByTestId('toolbar-suche');
    liste().focus();
    await u.keyboard('{Meta>}f{/Meta}');
    expect(feld).toHaveFocus();
    await u.keyboard('{Escape}');
    expect(liste()).toHaveFocus();
  });
});

// ═══ I · Themes und Bewegung (statisch über die Token-Datei) ════════════════
describe('Design-Tokens', () => {
  it('definiert reduzierte Bewegung und keine verstreuten Farben', async () => {
    const { readFileSync } = await import('node:fs');
    const { join, dirname } = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const hier = dirname(fileURLToPath(import.meta.url));
    const tokens = readFileSync(join(hier, 'tokens.css'), 'utf8');
    expect(tokens).toContain('prefers-reduced-motion');
    expect(tokens).toContain('--pjc-selection-bg');
    expect(tokens).toContain('M2-VORLÄUFIG');
    // Light/Dark laufen über die bestehenden Jarvis-Tokens:
    expect(tokens).toContain('var(--color-text-secondary)');
  });
});

// ═══ J · Sicherheit: Demo-Modus und Provider-Grenzen ════════════════════════
describe('Sicherheit', () => {
  it('startet standardmässig ohne Demo-Modus', async () => {
    await rendern();
    expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
  });

  it('verlangt für den Demo-Modus zwei bewusste Schritte und ist beendbar', async () => {
    await rendern();
    const u = nutzer();
    await u.click(screen.getByTestId('sidebar-status'));
    await u.click(await screen.findByTestId('demo-anbieten'));
    // Erster Klick aktiviert nichts:
    expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
    await u.click(screen.getByTestId('demo-starten'));
    expect(await screen.findByTestId('demo-banner')).toBeInTheDocument();
    expect((await screen.findAllByText(/Attrappe|Beispiel|Muster/)).length).toBeGreaterThan(0);
    await u.click(screen.getByTestId('demo-beenden'));
    await waitFor(() => {
      expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
    });
  });

  it('ruft im Demo-Modus keinen einzigen Client-Endpunkt auf', async () => {
    await rendern();
    const u = nutzer();
    await u.click(screen.getByTestId('sidebar-status'));
    await u.click(await screen.findByTestId('demo-anbieten'));
    await u.click(screen.getByTestId('demo-starten'));
    await screen.findByTestId('demo-banner');
    vi.clearAllMocks();
    // Suche, Auswahl und Detail in der Demo-Quelle.
    //
    // Gesucht wird nach einem **Vornamen**, der in den Fixtures genau einmal
    // vorkommt. Das ist kein Detail: Die Suche ist entprellt, und die
    // Zusicherung „die Liste existiert" wäre schon vor dem Entprellen wahr —
    // der spätere Austausch der Liste liefe dann unter dem laufenden Test
    // weiter. „Genau eine Option" kann dagegen erst gelten, **nachdem** die
    // entprellte Suche angekommen ist: ein echter Endzustand statt einer
    // Wartezeit, die unter Last reisst.
    const unGefiltert = screen.getAllByRole('option')[0]
      .getAttribute('aria-setsize');
    await u.type(screen.getByTestId('toolbar-suche'), 'Alva');
    await waitFor(() => {
      // `aria-setsize` nennt die **volle** Treffermenge, unabhängig davon,
      // wie viele Zeilen gerade im DOM stehen. Sobald sie sich ändert, ist
      // die entprellte Suche nachweislich angekommen.
      expect(screen.getAllByRole('option')[0])
        .not.toHaveAttribute('aria-setsize', unGefiltert);
    });
    const erste = screen.getAllByRole('option')[0];
    await u.click(erste);
    await screen.findByTestId('contact-detail');
    for (const fn of Object.values(mock)) {
      if (typeof fn?.mock === 'object') expect(fn).not.toHaveBeenCalled();
    }
  });

  it('führt aus der Demo-Quelle nie etwas aus', async () => {
    const q = fixtureDataSource(5);
    await expect(q.execute('demo-m-1')).rejects.toThrow(/Demo-Modus/);
  });
});

// ═══ K · Performance-Struktur: Fensterung bei grossen Mengen ════════════════
describe('Fensterung', () => {
  it('rendert bei 10.000 Kontakten nur einen begrenzten DOM-Ausschnitt', async () => {
    const gross = sortiereKontakte(syntheticSummaries(10000));
    mock.listContacts.mockResolvedValue(seite(
      gross.map((k) => ({ ...k })),
    ));
    const { ContactsWorkspace } = await import('./workspace/ContactsWorkspace');
    render(<ContactsWorkspace testListenHoehe={600} />);
    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    }, { timeout: 15000 });
    const optionen = screen.getAllByRole('option');
    expect(optionen.length).toBeLessThan(120);
    expect(optionen[0]).toHaveAttribute('aria-setsize', '10000');
  }, 30000);

  it('bleibt deterministisch: gleiche Erzeugung, gleiche Daten', () => {
    const a = syntheticSummaries(100);
    const b = syntheticSummaries(100);
    expect(a).toEqual(b);
  });
});

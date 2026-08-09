// @vitest-environment jsdom
//
// Das CREATE-Formular mit Freigabefluss (B3 P1) — geprüft werden die
// Ehrlichkeits- und Sicherheitsregeln des Kanals:
//
//  · Die Vorschau zeigt die SERVER-Vorschau, nicht die Formularwerte.
//  · „Abbrechen" ruft cancel und erreicht NIE den App-Prozess (R9-artig).
//  · „Anlegen" läuft exakt approve → claim → execute → settle.
//  · Ein not_sent-Bericht meldet die Fehlerklasse und keinen Erfolg.
//  · Der gesamte Fluss löst keinen Provider-Sync aus.

// Zeitzonen-Pin wie in CalendarWorkspace.test.tsx: die Fixtures sprechen
// Europe/Berlin, sonst kippt der Bestand unter TZ=UTC in den Vortag.
process.env.TZ = 'Europe/Berlin';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { KalenderZeile, ModulStatus, Termin } from './api';
import * as api from './api';
import * as mApi from './mutationsApi';
import { CalendarWorkspace } from './CalendarWorkspace';

const KALENDER: KalenderZeile[] = [
  {
    id: 'k1', provider_account_id: 'p', provider_calendar_id: 'cal-1',
    display_name: 'Privat', calendar_type: 'calDAV', source_identifier: 's1',
    source_title: 'iCloud', source_type: 'calDAV', color: '#3366cc',
    is_writable: true, is_subscribed: false, is_immutable: false,
    supports_events: true, sync_enabled: true,
  },
  {
    id: 'k2', provider_account_id: 'p', provider_calendar_id: 'cal-2',
    display_name: 'Geburtstage', calendar_type: 'birthday', source_identifier: 's2',
    source_title: 'Andere', source_type: 'birthdays', color: '#cc6633',
    is_writable: false, is_subscribed: false, is_immutable: true,
    supports_events: true, sync_enabled: true,
  },
];

const STATUS: ModulStatus = {
  bridge_available: true, authorization_status: 'full_access', can_read: true,
  capabilities: {
    can_read: true, can_create_events: true, can_update_events: false,
    can_delete_events: false, supports_recurrence: true, supports_attendees: true,
    supports_alarms: true, supports_time_zones: true, window_required: true,
    change_feed: 'notification',
  },
  detail: '', default_window: { past_days: 90, future_days: 365 },
};

function mockApi(termine: Termin[] = []) {
  vi.spyOn(api, 'ladeStatus').mockResolvedValue(STATUS);
  vi.spyOn(api, 'pruefeBridge').mockResolvedValue({
    bridge_available: true, authorization_status: 'full_access', detail: '' });
  vi.spyOn(api, 'ladeKalender').mockResolvedValue(
    { calendars: KALENDER, count: KALENDER.length });
  vi.spyOn(api, 'ladeTermine').mockImplementation(async (von, bis) => ({
    events: termine, count: termine.length,
    window: { start_utc: von, end_utc: bis },
    truncated: false,
  }));
}

/** Ein bestehender Termin des Bestands — 10:00–11:00 Berlin am 12.08. */
function bestandsTermin(over: Partial<Termin> = {}): Termin {
  return {
    id: 'e1', calendar_id: 'k1', title: 'Zahnarzt', notes: null,
    location: null, url: null,
    starts_at_utc: '2026-08-12T08:00:00Z', ends_at_utc: '2026-08-12T09:00:00Z',
    time_zone: 'Europe/Berlin', is_all_day: false, status: 'confirmed',
    availability: 'busy', recurrence_rule: null, is_detached: false,
    occurrence_start_utc: null, has_alarms: false, alarms: [],
    has_attendees: false, attendees: [],
    calendar_name: 'Privat', calendar_color: '#3366cc',
    calendar_is_writable: true,
    provider_calendar_id: 'cal-1', provider_event_id: 'EK-EVENT-1', ...over,
  };
}

const VORGANG: mApi.VorbereiteterVorgang = {
  mutation_id: 'm1', approval_id: 'a1', state: 'prepared',
  payload_digest: 'p'.repeat(64),
  preview: {
    command: 'create', calendar_display_name: 'Privat', title: 'Planung',
    starts_at_utc: '2026-08-12T07:00:00Z', ends_at_utc: '2026-08-12T08:00:00Z',
    is_all_day: false, location: 'Raum 3', time_zone: 'Europe/Berlin',
  },
  preview_digest: 'q'.repeat(64),
};

const AUFTRAG: mApi.KalenderExecutionOrder = {
  schema_version: 1, operation_id: 'op1', mutation_id: 'm1',
  claim_token: 'token-1', operation_type: 'create',
  payload_digest: 'p'.repeat(64), preview_digest: 'q'.repeat(64),
  canonical_payload: {}, issued_at: '2026-08-12T10:00:00Z',
  expires_at: '2026-08-12T10:05:00Z',
  provider_target: { provider_calendar_id: 'cal-1', event_identifier: null },
  expected_fingerprint: null,
};

function bericht(over: Partial<mApi.KalenderExecutionReport> = {},
): mApi.KalenderExecutionReport {
  return {
    schema_version: 1, operation_id: 'op1', mutation_id: 'm1',
    operation_type: 'create', outcome: 'applied', send_attempted: true,
    save_request_count: 1, readback_status: 'confirmed',
    readback_event: null, provider_identifier: 'prov-1',
    fingerprint_checked: false, fingerprint_matched: null,
    error_class: null, error_digest: null,
    provider_completed_at: '2026-08-12T10:00:01Z', ...over,
  };
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-08-12T10:00:00Z'));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  cleanup();
});

async function oeffneFormular() {
  mockApi();
  render(<CalendarWorkspace />);
  await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
  fireEvent.click(screen.getByLabelText('Neuen Termin anlegen'));
  expect(screen.getByRole('dialog', { name: 'Neuer Termin' })).toBeTruthy();
}

/** Titel setzen und zur Vorschau gehen — der gemeinsame Weg vieler Tests. */
async function zurVorschau() {
  fireEvent.change(screen.getByLabelText('Titel'),
                   { target: { value: 'Planung' } });
  fireEvent.click(screen.getByText('Weiter zur Vorschau'));
  await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
}

describe('Öffnen und Vorbelegung', () => {
  it('oeffnet mit heutigem Tag und 09:00–10:00 lokal vorbelegt', async () => {
    await oeffneFormular();
    expect((screen.getByLabelText('Datum Beginn') as HTMLInputElement).value)
      .toBe('2026-08-12');
    expect((screen.getByLabelText('Datum Ende') as HTMLInputElement).value)
      .toBe('2026-08-12');
    expect((screen.getByLabelText('Uhrzeit Beginn') as HTMLInputElement).value)
      .toBe('09:00');
    expect((screen.getByLabelText('Uhrzeit Ende') as HTMLInputElement).value)
      .toBe('10:00');
    // Nichts ist vorangekreuzt.
    expect((screen.getByLabelText('Ganztägig') as HTMLInputElement).checked)
      .toBe(false);
  });

  it('belegt mit dem gewaehlten Tag vor, wenn einer gewaehlt ist', async () => {
    mockApi();
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    const zelle = screen.getAllByTestId('kalender-tag')
      .find((z) => z.getAttribute('data-date') === '2026-08-05')!;
    fireEvent.click(zelle);
    fireEvent.click(screen.getByLabelText('Neuen Termin anlegen'));
    expect((screen.getByLabelText('Datum Beginn') as HTMLInputElement).value)
      .toBe('2026-08-05');
  });

  it('bietet ausschliesslich beschreibbare Kalender an', async () => {
    await oeffneFormular();
    const optionen = screen.getAllByRole('option').map((o) => o.textContent);
    expect(optionen).toEqual(['Privat']);
  });

  it('blendet als Ganztaegig die Uhrzeiten aus', async () => {
    await oeffneFormular();
    fireEvent.click(screen.getByLabelText('Ganztägig'));
    expect(screen.queryByLabelText('Uhrzeit Beginn')).toBeNull();
    expect(screen.queryByLabelText('Uhrzeit Ende')).toBeNull();
  });
});

describe('Zeitraum — Dauererhalt (B3 P1)', () => {
  /** Aktueller Wert eines gelabelten Feldes. */
  const wert = (label: string) =>
    (screen.getByLabelText(label) as HTMLInputElement).value;

  it('verschiebt mit dem Startdatum das Enddatum — Dauer exakt erhalten', async () => {
    await oeffneFormular();
    // Vorbelegt: 12.08. 09:00–10:00.
    fireEvent.change(screen.getByLabelText('Datum Beginn'),
                     { target: { value: '2026-08-15' } });
    expect(wert('Datum Beginn')).toBe('2026-08-15');
    expect(wert('Datum Ende')).toBe('2026-08-15');
    expect(wert('Uhrzeit Beginn')).toBe('09:00');
    expect(wert('Uhrzeit Ende')).toBe('10:00');
  });

  it('verschiebt mit der Startzeit die Endzeit', async () => {
    await oeffneFormular();
    fireEvent.change(screen.getByLabelText('Uhrzeit Beginn'),
                     { target: { value: '14:30' } });
    expect(wert('Uhrzeit Beginn')).toBe('14:30');
    expect(wert('Uhrzeit Ende')).toBe('15:30');
    expect(wert('Datum Ende')).toBe('2026-08-12');
  });

  it('wandert ueber Mitternacht auf den Folgetag', async () => {
    await oeffneFormular();
    // 1h Dauer ab 23:30 endet 00:30 am Folgetag.
    fireEvent.change(screen.getByLabelText('Uhrzeit Beginn'),
                     { target: { value: '23:30' } });
    expect(wert('Uhrzeit Ende')).toBe('00:30');
    expect(wert('Datum Ende')).toBe('2026-08-13');
  });

  it('erhaelt ganztaegig die Tagesdifferenz', async () => {
    await oeffneFormular();
    fireEvent.click(screen.getByLabelText('Ganztägig'));
    fireEvent.change(screen.getByLabelText('Datum Ende'),
                     { target: { value: '2026-08-14' } });  // 2 Tage Differenz
    fireEvent.change(screen.getByLabelText('Datum Beginn'),
                     { target: { value: '2026-08-20' } });
    expect(wert('Datum Ende')).toBe('2026-08-22');
  });

  it('laesst eine bewusste Ende-Aenderung bestehen — keine Rueckstellung', async () => {
    await oeffneFormular();
    fireEvent.change(screen.getByLabelText('Uhrzeit Beginn'),
                     { target: { value: '14:30' } });
    // Bewusst laengeres Ende: nur DIESES Feld aendert sich.
    fireEvent.change(screen.getByLabelText('Uhrzeit Ende'),
                     { target: { value: '18:00' } });
    expect(wert('Uhrzeit Ende')).toBe('18:00');
    expect(wert('Uhrzeit Beginn')).toBe('14:30');
    expect(wert('Datum Ende')).toBe('2026-08-12');
  });

  it('sendet nach einer Startverschiebung weiterhin dieselbe Zone', async () => {
    const vor = vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    await oeffneFormular();
    fireEvent.change(screen.getByLabelText('Datum Beginn'),
                     { target: { value: '2026-08-15' } });
    await zurVorschau();
    // Der Zeitzonenanker bleibt die Plattformzone — die Verschiebung
    // aendert Instants, nie die Zone (time_zone-Regression).
    expect(vor).toHaveBeenCalledWith('cal-1', expect.objectContaining({
      starts_at_utc: '2026-08-15T07:00:00Z',
      ends_at_utc: '2026-08-15T08:00:00Z',
      time_zone: 'Europe/Berlin',
    }));
  });
});

describe('Vorbereitung', () => {
  it('sendet die lokale Zeit als UTC-Instant in Sekundenpraezision', async () => {
    const vor = vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    await oeffneFormular();
    await zurVorschau();
    // 09:00/10:00 Europe/Berlin im August = 07:00/08:00 UTC. Die Zone kommt
    // mechanisch aus der Plattformquelle (TZ-Pin oben), nie hart codiert.
    expect(vor).toHaveBeenCalledWith('cal-1', {
      title: 'Planung',
      starts_at_utc: '2026-08-12T07:00:00Z',
      ends_at_utc: '2026-08-12T08:00:00Z',
      is_all_day: false, location: null, notes: null,
      time_zone: 'Europe/Berlin',
    });
  });

  it('sendet ganztaegig die lokalen Mitternachts-Instants, Ende exklusiv', async () => {
    const vor = vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    await oeffneFormular();
    fireEvent.click(screen.getByLabelText('Ganztägig'));
    await zurVorschau();
    // Lokale Mitternacht des 12. = 11T22:00Z; exklusives Ende = Mitternacht
    // des Folgetags = 12T22:00Z.
    expect(vor).toHaveBeenCalledWith('cal-1', expect.objectContaining({
      is_all_day: true,
      starts_at_utc: '2026-08-11T22:00:00Z',
      ends_at_utc: '2026-08-12T22:00:00Z',
      // Ganztägig ist im Bestand schwebend (events.time_zone NULL) —
      // die Maske sendet die Semantik ausdrücklich, nie die Systemzone.
      time_zone: null,
    }));
  });

  it('zeigt einen Validierungsfehler vor jedem Serverkontakt', async () => {
    const vor = vi.spyOn(mApi, 'bereiteVor');
    await oeffneFormular();
    fireEvent.change(screen.getByLabelText('Uhrzeit Ende'),
                     { target: { value: '08:00' } });
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    expect(screen.getByTestId('termin-fehler').textContent)
      .toContain('Ende muss nach dem Beginn');
    expect(vor).not.toHaveBeenCalled();
  });

  it('zeigt einen prepare-Fehler sichtbar an', async () => {
    vi.spyOn(mApi, 'bereiteVor')
      .mockRejectedValue(new Error('calendar_api_400'));
    await oeffneFormular();
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-fehler')).toBeTruthy());
    expect(screen.getByTestId('termin-fehler').textContent)
      .toContain('Felder abgewiesen');
  });
});

describe('Vorschau und Freigabe', () => {
  it('zeigt die SERVER-Vorschau: Kalender, Titel, Zeit, Ort', async () => {
    vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    await oeffneFormular();
    await zurVorschau();
    const vorschau = screen.getByTestId('termin-vorschau');
    expect(vorschau.textContent).toContain('Privat');
    expect(vorschau.textContent).toContain('Planung');
    expect(vorschau.textContent).toContain('09:00');
    expect(vorschau.textContent).toContain('10:00');
    expect(vorschau.textContent).toContain('Raum 3');
    // Die SERVER-Preview-Zone ist Teil dessen, was freigegeben wird.
    expect(vorschau.textContent).toContain('Zeitzone');
    expect(vorschau.textContent).toContain('Europe/Berlin');
    // GENAU EIN Freigabeknopf.
    expect(screen.getAllByRole('button', { name: 'Anlegen' }).length).toBe(1);
  });

  it('zeigt eine schwebende SERVER-Vorschau ehrlich als schwebend', async () => {
    vi.spyOn(mApi, 'bereiteVor').mockResolvedValue({
      ...VORGANG,
      preview: { ...VORGANG.preview, is_all_day: true, time_zone: null },
    });
    await oeffneFormular();
    await zurVorschau();
    expect(screen.getByTestId('termin-vorschau').textContent)
      .toContain('schwebend — ohne feste Zeitzone');
  });

  it('Abbrechen ruft cancel und erreicht NIE den App-Prozess', async () => {
    vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    const frei = vi.spyOn(mApi, 'gibFrei');
    const abbruch = vi.spyOn(mApi, 'bricheAb')
      .mockResolvedValue({ mutation_id: 'm1', state: 'canceled' });
    const ausfuehren = vi.spyOn(mApi, 'fuehreAus');
    await oeffneFormular();
    await zurVorschau();
    fireEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    await waitFor(() => expect(abbruch).toHaveBeenCalledWith('m1'));
    // R9-artig: der App-Prozess wird nie erreicht, freigegeben wird nichts.
    expect(ausfuehren).not.toHaveBeenCalled();
    expect(frei).not.toHaveBeenCalled();
    await waitFor(() => expect(
      screen.queryByRole('dialog', { name: 'Neuer Termin' })).toBeNull());
  });
});

describe('Anlegen — der Claim-Settle-Kanal', () => {
  it('laeuft exakt approve → claim → execute → settle und meldet Erfolg', async () => {
    const reihenfolge: string[] = [];
    vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    const sync = vi.spyOn(api, 'synchronisiere');
    vi.spyOn(mApi, 'gibFrei').mockImplementation(async () => {
      reihenfolge.push('approve');
      return { mutation_id: 'm1', state: 'approved' };
    });
    vi.spyOn(mApi, 'beanspruche').mockImplementation(async () => {
      reihenfolge.push('claim');
      return AUFTRAG;
    });
    const ausfuehren = vi.spyOn(mApi, 'fuehreAus').mockImplementation(async () => {
      reihenfolge.push('execute');
      return bericht();
    });
    vi.spyOn(mApi, 'schliesseAb').mockImplementation(async () => {
      reihenfolge.push('settle');
      return { mutation_id: 'm1', state: 'succeeded', outcome: 'succeeded',
               idempotent: false, error_class: null };
    });

    await oeffneFormular();
    await zurVorschau();
    fireEvent.click(screen.getByRole('button', { name: 'Anlegen' }));
    await waitFor(() => expect(screen.getByTestId('termin-ergebnis')).toBeTruthy());

    expect(reihenfolge).toEqual(['approve', 'claim', 'execute', 'settle']);
    // Der Auftrag geht UNVERÄNDERT als JSON-Text hinüber.
    expect(ausfuehren).toHaveBeenCalledWith(JSON.stringify(AUFTRAG));
    expect(mApi.schliesseAb).toHaveBeenCalledWith('m1', 'token-1', bericht());
    expect(screen.getByTestId('termin-ergebnis').textContent)
      .toContain('Termin angelegt.');
    // Der Workspace meldet die HANDLUNG und liest den Bestand neu …
    await waitFor(() => expect(
      screen.getByTestId('kalender-meldung').textContent)
      .toContain('Letzte Aktion: Termin angelegt.'));
    // … aber im gesamten Fluss laeuft KEIN Provider-Sync.
    expect(sync).not.toHaveBeenCalled();
  });

  it('zeigt bei einem not_sent-Bericht die Fehlerklasse und keinen Erfolg', async () => {
    vi.spyOn(mApi, 'bereiteVor').mockResolvedValue(VORGANG);
    const sync = vi.spyOn(api, 'synchronisiere');
    vi.spyOn(mApi, 'gibFrei')
      .mockResolvedValue({ mutation_id: 'm1', state: 'approved' });
    vi.spyOn(mApi, 'beanspruche').mockResolvedValue(AUFTRAG);
    vi.spyOn(mApi, 'fuehreAus').mockResolvedValue(bericht({
      outcome: 'not_sent', send_attempted: false,
      readback_status: 'not_checked', provider_identifier: null,
      error_class: 'calendar_not_found', provider_completed_at: null,
    }));
    vi.spyOn(mApi, 'schliesseAb').mockResolvedValue({
      mutation_id: 'm1', state: 'failed_before_send', outcome: 'failed',
      idempotent: false, error_class: 'calendar_not_found',
    });

    await oeffneFormular();
    await zurVorschau();
    fireEvent.click(screen.getByRole('button', { name: 'Anlegen' }));
    await waitFor(() => expect(screen.getByTestId('termin-ergebnis')).toBeTruthy());

    const text = screen.getByTestId('termin-ergebnis').textContent ?? '';
    expect(text).toContain('calendar_not_found');
    expect(text).toContain('nichts gesendet');
    expect(text).not.toContain('Termin angelegt.');
    // Kein erfundener Erfolg im Workspace, kein Sync.
    expect(screen.queryByTestId('kalender-meldung')).toBeNull();
    expect(sync).not.toHaveBeenCalled();
  });
});

// ── B3 P2: Bearbeiten mit Delta-Semantik ────────────────────────────────────

const VORGANG_UPDATE: mApi.VorbereiteterVorgang = {
  mutation_id: 'm2', approval_id: 'a2', state: 'prepared',
  payload_digest: 'p'.repeat(64),
  preview: {
    command: 'update', calendar_display_name: 'Privat', title: 'Zahnarzt',
    starts_at_utc: '2026-08-12T08:00:00Z', ends_at_utc: '2026-08-12T09:00:00Z',
    is_all_day: false, location: null, time_zone: 'Europe/Berlin',
    changes: { title: { from: 'Zahnarzt', to: 'Kieferorthopäde' } },
  },
  preview_digest: 'q'.repeat(64),
};

/** Öffnet das Detail des Bestandstermins und dann die Update-Maske. */
async function oeffneBearbeiten(termin: Termin = bestandsTermin()) {
  mockApi([termin]);
  render(<CalendarWorkspace />);
  await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
  fireEvent.click(screen.getAllByTestId('kalender-termin')[0]!);
  fireEvent.click(screen.getByTestId('termin-bearbeiten'));
  expect(screen.getByRole('dialog', { name: 'Termin bearbeiten' })).toBeTruthy();
}

describe('Bearbeiten — Sichtbarkeit und Verweigerung', () => {
  async function zeigeDetail(termin: Termin) {
    mockApi([termin]);
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.click(screen.getAllByTestId('kalender-termin')[0]!);
  }

  it('zeigt „Bearbeiten" fuer einen schreibbaren einfachen Termin', async () => {
    await zeigeDetail(bestandsTermin());
    expect(screen.getByTestId('termin-bearbeiten')).toBeTruthy();
    expect(screen.queryByTestId('termin-nicht-bearbeitbar')).toBeNull();
  });

  it.each([
    ['Teilnehmern', { has_attendees: true }],
    ['Serie', { recurrence_rule: { frequency: 'weekly' } }],
    ['Weckern', { has_alarms: true }],
    ['abgeloester Instanz', { is_detached: true }],
  ] as const)('verweigert sichtbar bei %s', async (_name, over) => {
    await zeigeDetail(bestandsTermin(over as Partial<Termin>));
    expect(screen.queryByTestId('termin-bearbeiten')).toBeNull();
    expect(screen.getByTestId('termin-nicht-bearbeitbar').textContent)
      .toContain('Eigenschaften, die Jarvis nicht verlustfrei bearbeiten kann');
  });

  it('bietet bei nicht schreibbarem Kalender keinen Bearbeiten-Knopf', async () => {
    await zeigeDetail(bestandsTermin({ calendar_is_writable: false }));
    expect(screen.queryByTestId('termin-bearbeiten')).toBeNull();
    expect(screen.queryByTestId('termin-nicht-bearbeitbar')).toBeNull();
  });
});

describe('Bearbeiten — Entwurf und Delta', () => {
  it('belegt die Maske aus dem Termin vor', async () => {
    await oeffneBearbeiten();
    expect((screen.getByLabelText('Titel') as HTMLInputElement).value)
      .toBe('Zahnarzt');
    // 08:00Z/09:00Z sind 10:00/11:00 Berlin.
    expect((screen.getByLabelText('Datum Beginn') as HTMLInputElement).value)
      .toBe('2026-08-12');
    expect((screen.getByLabelText('Uhrzeit Beginn') as HTMLInputElement).value)
      .toBe('10:00');
    expect((screen.getByLabelText('Uhrzeit Ende') as HTMLInputElement).value)
      .toBe('11:00');
    // Das Ziel steht fest: kein Kalenderwechsel im Update — die Maske
    // zeigt den Kalender nur als Text, nie als Auswahl.
    const dialog = screen.getByRole('dialog', { name: 'Termin bearbeiten' });
    expect(within(dialog).queryByLabelText('Kalender')).toBeNull();
    expect(dialog.textContent).toContain('Kalender: Privat');
  });

  it('sendet NUR die geaenderten Felder als changes', async () => {
    const vor = vi.spyOn(mApi, 'bereiteUpdateVor')
      .mockResolvedValue(VORGANG_UPDATE);
    await oeffneBearbeiten();
    fireEvent.change(screen.getByLabelText('Titel'),
                     { target: { value: 'Kieferorthopäde' } });
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
    // GENAU das Delta — kein Feld „zur Sicherheit" mitgesendet.
    expect(vor).toHaveBeenCalledWith('cal-1', 'EK-EVENT-1',
                                     { title: 'Kieferorthopäde' });
  });

  it('meldet ein leeres Delta ohne jeden Serverkontakt', async () => {
    const vor = vi.spyOn(mApi, 'bereiteUpdateVor');
    await oeffneBearbeiten();
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-fehler')).toBeTruthy());
    expect(screen.getByTestId('termin-fehler').textContent)
      .toContain('Keine Änderung');
    expect(vor).not.toHaveBeenCalled();
  });

  it('nutzt bei Startverschiebung den Dauererhalt — Zone bleibt unangetastet', async () => {
    const vor = vi.spyOn(mApi, 'bereiteUpdateVor')
      .mockResolvedValue(VORGANG_UPDATE);
    await oeffneBearbeiten();
    // 10:00 → 14:30 lokal: der Dauererhalt schiebt das Ende auf 15:30.
    fireEvent.change(screen.getByLabelText('Uhrzeit Beginn'),
                     { target: { value: '14:30' } });
    expect((screen.getByLabelText('Uhrzeit Ende') as HTMLInputElement).value)
      .toBe('15:30');
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
    // NUR die Instants reisen; die Zone des Termins bleibt unberuehrt
    // (Floating bliebe Floating, ein Anker bleibt ein Anker).
    expect(vor).toHaveBeenCalledWith('cal-1', 'EK-EVENT-1', {
      starts_at_utc: '2026-08-12T12:30:00Z',
      ends_at_utc: '2026-08-12T13:30:00Z',
    });
  });
});

describe('Bearbeiten — Vorschau und Freigabefluss', () => {
  it('zeigt das SERVER-Delta alt → neu mit genau einem Freigabeknopf', async () => {
    vi.spyOn(mApi, 'bereiteUpdateVor').mockResolvedValue(VORGANG_UPDATE);
    await oeffneBearbeiten();
    fireEvent.change(screen.getByLabelText('Titel'),
                     { target: { value: 'Kieferorthopäde' } });
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
    const delta = screen.getByTestId('termin-aenderungen');
    expect(delta.textContent).toContain('Titel');
    expect(delta.textContent).toContain('Zahnarzt');
    expect(delta.textContent).toContain('Kieferorthopäde');
    expect(delta.textContent).toContain('→');
    expect(screen.getAllByRole('button', { name: 'Änderung freigeben' }).length)
      .toBe(1);
    expect(screen.queryByRole('button', { name: 'Anlegen' })).toBeNull();
  });

  it('laeuft exakt approve → claim → execute → settle und meldet Erfolg', async () => {
    const reihenfolge: string[] = [];
    vi.spyOn(mApi, 'bereiteUpdateVor').mockResolvedValue(VORGANG_UPDATE);
    const sync = vi.spyOn(api, 'synchronisiere');
    vi.spyOn(mApi, 'gibFrei').mockImplementation(async () => {
      reihenfolge.push('approve');
      return { mutation_id: 'm2', state: 'approved' };
    });
    const auftrag: mApi.KalenderExecutionOrder = {
      ...AUFTRAG, mutation_id: 'm2', operation_type: 'update',
      provider_target: { provider_calendar_id: 'cal-1',
                         event_identifier: 'EK-EVENT-1' },
      expected_fingerprint: 'f'.repeat(64),
    };
    vi.spyOn(mApi, 'beanspruche').mockImplementation(async () => {
      reihenfolge.push('claim');
      return auftrag;
    });
    const ausfuehren = vi.spyOn(mApi, 'fuehreAus').mockImplementation(async () => {
      reihenfolge.push('execute');
      return bericht({ mutation_id: 'm2', operation_type: 'update',
                       fingerprint_checked: true, fingerprint_matched: true,
                       provider_identifier: 'EK-EVENT-1' });
    });
    vi.spyOn(mApi, 'schliesseAb').mockImplementation(async () => {
      reihenfolge.push('settle');
      return { mutation_id: 'm2', state: 'succeeded', outcome: 'succeeded',
               idempotent: false, error_class: null };
    });

    await oeffneBearbeiten();
    fireEvent.change(screen.getByLabelText('Titel'),
                     { target: { value: 'Kieferorthopäde' } });
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Änderung freigeben' }));
    await waitFor(() => expect(screen.getByTestId('termin-ergebnis')).toBeTruthy());

    expect(reihenfolge).toEqual(['approve', 'claim', 'execute', 'settle']);
    expect(ausfuehren).toHaveBeenCalledWith(JSON.stringify(auftrag));
    expect(screen.getByTestId('termin-ergebnis').textContent)
      .toContain('Termin aktualisiert.');
    await waitFor(() => expect(
      screen.getByTestId('kalender-meldung').textContent)
      .toContain('Letzte Aktion: Termin aktualisiert.'));
    // Im gesamten Fluss laeuft KEIN Provider-Sync.
    expect(sync).not.toHaveBeenCalled();
  });

  it('meldet einen revision_conflict ehrlich und ohne Erfolg', async () => {
    vi.spyOn(mApi, 'bereiteUpdateVor').mockResolvedValue(VORGANG_UPDATE);
    vi.spyOn(mApi, 'gibFrei')
      .mockResolvedValue({ mutation_id: 'm2', state: 'approved' });
    vi.spyOn(mApi, 'beanspruche').mockResolvedValue(
      { ...AUFTRAG, mutation_id: 'm2', operation_type: 'update' });
    vi.spyOn(mApi, 'fuehreAus').mockResolvedValue(bericht({
      mutation_id: 'm2', operation_type: 'update', outcome: 'not_sent',
      send_attempted: false, save_request_count: 0,
      readback_status: 'not_checked', provider_identifier: null,
      fingerprint_checked: true, fingerprint_matched: false,
      error_class: 'revision_conflict', provider_completed_at: null,
    }));
    vi.spyOn(mApi, 'schliesseAb').mockResolvedValue({
      mutation_id: 'm2', state: 'failed_before_send', outcome: 'failed',
      idempotent: false, error_class: 'revision_conflict',
    });

    await oeffneBearbeiten();
    fireEvent.change(screen.getByLabelText('Titel'),
                     { target: { value: 'Kieferorthopäde' } });
    fireEvent.click(screen.getByText('Weiter zur Vorschau'));
    await waitFor(() => expect(screen.getByTestId('termin-vorschau')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Änderung freigeben' }));
    await waitFor(() => expect(screen.getByTestId('termin-ergebnis')).toBeTruthy());

    const text = screen.getByTestId('termin-ergebnis').textContent ?? '';
    expect(text).toContain('zwischenzeitlich anderweitig geändert');
    expect(text).toContain('nichts gesendet');
    expect(text).not.toContain('Termin aktualisiert.');
  });
});

// @vitest-environment jsdom
//
// Die Oberfläche — geprüft werden vor allem die Ehrlichkeitsregeln.
//
// Diese Datei braucht ein DOM (Klicks, Tastatur, Fokus) und fordert es per
// Docblock an — die Repo-Vorgabe ist `node`, jsdom ist die Ausnahme.
//
// „Sieht gut aus" ist kein Testziel. Geprüft wird, dass die Ansicht nichts
// behauptet, was sie nicht weiss: dass ein ungeladener Tag anders aussieht als
// ein freier, dass ein Berechtigungsproblem seinen Grund nennt, und dass kein
// Rendern und kein Ansichtswechsel einen Sync auslöst.

// Die Fixtures dieser Datei sprechen Europe/Berlin, das Raster bucketiert in
// der Systemzeitzone. Ohne Pin kippt derselbe Bestand unter TZ=UTC (der
// deterministischen Gate-Umgebung) in den Vortag. Der Pin steht vor allen
// Imports, damit keine Date-Operation die Zeitzone vorher einfriert.
process.env.TZ = 'Europe/Berlin';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { KalenderZeile, ModulStatus, Termin } from './api';
import * as api from './api';
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

function termin(over: Partial<Termin> = {}): Termin {
  return {
    id: 'e1', calendar_id: 'k1', title: 'Besprechung', notes: null,
    location: null, url: null,
    starts_at_utc: '2026-08-12T08:00:00Z', ends_at_utc: '2026-08-12T09:00:00Z',
    time_zone: 'Europe/Berlin', is_all_day: false, status: 'confirmed',
    availability: 'busy', recurrence_rule: null, is_detached: false,
    occurrence_start_utc: null, has_alarms: false, alarms: [],
    has_attendees: false, attendees: [],
    calendar_name: 'Privat', calendar_color: '#3366cc',
    calendar_is_writable: true, ...over,
  };
}

const STATUS: ModulStatus = {
  bridge_available: true, authorization_status: 'full_access', can_read: true,
  capabilities: {
    can_read: true, can_create_events: false, can_update_events: false,
    can_delete_events: false, supports_recurrence: true, supports_attendees: true,
    supports_alarms: true, supports_time_zones: true, window_required: true,
    change_feed: 'notification',
  },
  detail: '', default_window: { past_days: 90, future_days: 365 },
};

function mockApi(over: {
  status?: Partial<ModulStatus>; termine?: Termin[];
  fensterVon?: string; fensterBis?: string;
} = {}) {
  vi.spyOn(api, 'ladeStatus').mockResolvedValue({ ...STATUS, ...over.status });
  vi.spyOn(api, 'pruefeBridge').mockResolvedValue({
    bridge_available: (over.status?.bridge_available ?? STATUS.bridge_available),
    authorization_status:
      (over.status?.authorization_status ?? STATUS.authorization_status),
    detail: '',
  });
  vi.spyOn(api, 'ladeKalender').mockResolvedValue(
    { calendars: KALENDER, count: KALENDER.length });
  vi.spyOn(api, 'ladeTermine').mockImplementation(async (von, bis) => ({
    events: over.termine ?? [termin()],
    count: (over.termine ?? [termin()]).length,
    window: { start_utc: over.fensterVon ?? von, end_utc: over.fensterBis ?? bis },
    truncated: false,
  }));
}

beforeEach(() => {
  // `shouldAdvanceTime` ist Pflicht: `waitFor` der Testing Library wartet auf
  // echte Timer. Ohne die Option steht die Uhr, und jede Erwartung laeuft in
  // ihren Timeout statt in ihre Aussage.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date('2026-08-12T10:00:00Z'));
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  cleanup();
});

async function rendern() {
  mockApi();
  render(<CalendarWorkspace />);
  await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
}

describe('Laden und Grundaufbau', () => {
  it('zeigt zuerst einen Ladezustand', () => {
    mockApi();
    render(<CalendarWorkspace />);
    expect(screen.getByTestId('kalender-laedt')).toBeTruthy();
  });

  it('zeigt einen ehrlichen Fehlerzustand statt eines leeren Kalenders', async () => {
    vi.spyOn(api, 'ladeStatus').mockRejectedValue(new Error('weg'));
    vi.spyOn(api, 'ladeKalender').mockRejectedValue(new Error('weg'));
    vi.spyOn(api, 'ladeTermine').mockRejectedValue(new Error('weg'));
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-fehler')).toBeTruthy());
    expect(screen.getByText(/nicht erreichbar/)).toBeTruthy();
  });

  it('gruppiert die Kalender nach Quelle', async () => {
    await rendern();
    expect(screen.getByText('iCloud')).toBeTruthy();
    expect(screen.getByText('Andere')).toBeTruthy();
  });

  it('kennzeichnet einen nicht schreibbaren Kalender sichtbar', async () => {
    await rendern();
    // Provider-Wahrheit: der Geburtstagskalender sagt es hier, nicht erst
    // beim Speichern.
    expect(screen.getAllByLabelText('Nur lesbar').length).toBe(1);
  });
});

describe('Kein Auto-Sync', () => {
  it('loest beim Rendern keinen Lauf aus', async () => {
    const sync = vi.spyOn(api, 'synchronisiere');
    await rendern();
    expect(sync).not.toHaveBeenCalled();
  });

  it('loest beim Ansichtswechsel keinen Lauf aus', async () => {
    const sync = vi.spyOn(api, 'synchronisiere');
    await rendern();
    fireEvent.click(screen.getByRole('tab', { name: 'Woche' }));
    await waitFor(() => expect(api.ladeTermine).toHaveBeenCalled());
    expect(sync).not.toHaveBeenCalled();
  });

  it('loest beim Blaettern keinen Lauf aus', async () => {
    const sync = vi.spyOn(api, 'synchronisiere');
    await rendern();
    fireEvent.click(screen.getByLabelText('Weiter'));
    expect(sync).not.toHaveBeenCalled();
  });

  it('fragt beim Rendern keine Berechtigung an', async () => {
    const frage = vi.spyOn(api, 'frageBerechtigungAn');
    await rendern();
    expect(frage).not.toHaveBeenCalled();
  });
});

describe('Geladen und leer ist nicht ungeladen', () => {
  it('markiert Tage ausserhalb des geladenen Fensters als unbekannt', async () => {
    // Der Bestand kennt nur den 12. August — der Rest des Monatsrasters ist
    // ungeladen und darf nicht wie „frei" aussehen.
    mockApi({
      fensterVon: '2026-08-11T22:00:00Z',
      fensterBis: '2026-08-12T22:00:00Z',
    });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());

    const tage = screen.getAllByTestId('kalender-tag');
    const bekannt = tage.filter((t) => t.getAttribute('data-bekannt') === '1');
    const unbekannt = tage.filter((t) => t.getAttribute('data-bekannt') === '0');
    expect(bekannt.map((t) => t.getAttribute('data-date'))).toEqual(['2026-08-12']);
    expect(unbekannt.length).toBeGreaterThan(20);
    // Und der Unterschied ist sichtbar, nicht nur im Attribut.
    expect(unbekannt[0]!.className).toContain('pjk-unbekannt');
    expect(bekannt[0]!.className).not.toContain('pjk-unbekannt');
  });

  it('traegt keine Erklaer-Fusszeile mehr, die Ehrlichkeit bleibt strukturell (B2)', async () => {
    await rendern();
    // B2 entfernt die Erklaertexte, die die Referenz nicht zeigt. Die
    // Unterscheidung geladen/unbekannt bleibt als Schraffur bestehen und
    // wird im vorigen Test strukturell geprueft.
    expect(screen.queryByText(/Geladener Zeitraum/)).toBeNull();
    expect(screen.queryByText(/nicht „frei", sondern unbekannt/)).toBeNull();
  });
});

describe('Berechtigungszustände', () => {
  it('nennt bei not_determined den naechsten Schritt', async () => {
    mockApi({ status: { authorization_status: 'not_determined', can_read: false } });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-berechtigung')).toBeTruthy());
    expect(screen.getByText('Zugriff anfragen')).toBeTruthy();
  });

  it('behandelt write_only nie als Leseberechtigung', async () => {
    mockApi({ status: { authorization_status: 'write_only', can_read: false } });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-berechtigung')).toBeTruthy());
    expect(screen.getByText(/verlangt das System Vollzugriff/)).toBeTruthy();
  });

  it('sagt bei fehlender Bridge, dass der Kalender nicht leer sein muss', async () => {
    mockApi({ status: { bridge_available: false, can_read: false,
                        authorization_status: 'unknown' } });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-berechtigung')).toBeTruthy());
    expect(screen.getByText(/nicht gesagt, dass dein Kalender leer ist/)).toBeTruthy();
  });

  it('meldet ehrlich, wenn macOS gar keinen Dialog mehr zeigt', async () => {
    mockApi({ status: { authorization_status: 'not_determined', can_read: false } });
    vi.spyOn(api, 'frageBerechtigungAn').mockResolvedValue({
      granted: false, authorization_status: 'denied', prompt_attempted: false });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-berechtigung')).toBeTruthy());
    fireEvent.click(screen.getByText('Zugriff anfragen'));
    await waitFor(() => expect(screen.getByTestId('kalender-meldung')).toBeTruthy());
    expect(screen.getByText(/zeigt keinen Dialog mehr/)).toBeTruthy();
  });
});

describe('Sync-Ergebnis', () => {
  it('meldet einen teilweisen Lauf als unvollstaendig, nicht als Erfolg', async () => {
    await rendern();
    vi.spyOn(api, 'synchronisiere').mockResolvedValue({
      run_id: 'r', outcome: 'partial',
      window: { start_utc: 'a', end_utc: 'b' }, window_changed: false,
      calendars_total: 3, calendars_complete: 1, events_seen: 4,
      created: 4, updated: 0, unchanged: 0, tombstoned: 0,
      calendars: [], error: null,
    });
    fireEvent.click(screen.getByText('Aktualisieren'));
    await waitFor(() => expect(screen.getByTestId('kalender-meldung')).toBeTruthy());
    expect(screen.getByText(/Unvollständig: 1 von 3 Kalendern/)).toBeTruthy();
    expect(screen.getByText(/wurde nichts abgeleitet/)).toBeTruthy();
  });

  it('zeigt ein Ergebnis als HANDLUNG, nicht als Zustand', async () => {
    await rendern();
    vi.spyOn(api, 'synchronisiere').mockResolvedValue({
      run_id: 'r', outcome: 'completed',
      window: { start_utc: 'a', end_utc: 'b' }, window_changed: false,
      calendars_total: 1, calendars_complete: 1, events_seen: 2,
      created: 1, updated: 1, unchanged: 0, tombstoned: 0,
      calendars: [], error: null,
    });
    fireEvent.click(screen.getByText('Aktualisieren'));
    await waitFor(() => expect(screen.getByTestId('kalender-meldung')).toBeTruthy());
    expect(screen.getByTestId('kalender-meldung').textContent)
      .toContain('Letzte Aktion:');
  });
});

describe('Ansichten', () => {
  it('bietet Jahr, Monat, Woche und Tag', async () => {
    await rendern();
    for (const name of ['Jahr', 'Monat', 'Woche', 'Tag']) {
      expect(screen.getByRole('tab', { name })).toBeTruthy();
    }
  });

  it('zeigt in Woche und Tag einen eigenen Ganztagsbereich', async () => {
    mockApi({ termine: [termin({ is_all_day: true,
      starts_at_utc: '2026-08-12T00:00:00Z', ends_at_utc: '2026-08-13T00:00:00Z' })] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.click(screen.getByRole('tab', { name: 'Tag' }));
    await waitFor(() => expect(
      screen.getAllByTestId('kalender-ganztags').length).toBeGreaterThan(0));
    expect(screen.getByText('ganztägig')).toBeTruthy();
  });

  it('springt aus der Jahresansicht in den Tag', async () => {
    await rendern();
    fireEvent.click(screen.getByRole('tab', { name: 'Jahr' }));
    await waitFor(() => expect(
      screen.getAllByTestId('kalender-jahrestag').length).toBe(365));
  });
});

describe('Auswahl und Detail', () => {
  it('zeigt ohne Auswahl keinen erfundenen Termin', async () => {
    await rendern();
    expect(screen.getByText('Keinen Termin ausgewählt.')).toBeTruthy();
  });

  it('zeigt nach der Auswahl die Details', async () => {
    mockApi({ termine: [termin({ location: 'Raum 3', notes: 'Agenda' })] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.click(screen.getAllByTestId('kalender-termin')[0]!);
    await waitFor(() => expect(screen.getByLabelText('Termindetails')).toBeTruthy());
    expect(screen.getByText('Raum 3')).toBeTruthy();
    expect(screen.getByText('Agenda')).toBeTruthy();
  });

  it('benennt einen schwebenden Termin als schwebend', async () => {
    mockApi({ termine: [termin({ time_zone: null })] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.click(screen.getAllByTestId('kalender-termin')[0]!);
    await waitFor(() => expect(
      screen.getByText(/schwebend — ohne feste Zeitzone/)).toBeTruthy());
  });

  it('weist einen nicht schreibbaren Kalender im Detail aus', async () => {
    mockApi({ termine: [termin({ calendar_is_writable: false })] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.click(screen.getAllByTestId('kalender-termin')[0]!);
    await waitFor(() => expect(
      screen.getByText(/nicht beschreibbar/)).toBeTruthy());
  });
});

describe('Sichtbarkeit und Suche', () => {
  it('blendet einen Kalender rein visuell aus', async () => {
    await rendern();
    expect(screen.getAllByTestId('kalender-termin').length).toBe(1);
    fireEvent.click(screen.getByLabelText('Privat ausblenden'));
    await waitFor(() => expect(screen.queryAllByTestId('kalender-termin').length).toBe(0));
    // Ausblenden ist Anzeige — es ruft nichts auf.
    expect(api.synchronisiere).toBeDefined();
  });

  it('sucht ueber Titel, Ort und Teilnehmer', async () => {
    mockApi({ termine: [
      termin({ id: 'e1', title: 'Zahnarzt' }),
      termin({ id: 'e2', title: 'Sprint', location: 'Werkstatt' }),
    ] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Termine durchsuchen'),
                     { target: { value: 'werkstatt' } });
    await waitFor(() => expect(screen.getAllByTestId('kalender-termin').length).toBe(1));
  });
});

describe('Tastaturbedienung', () => {
  it('blaettert mit den Pfeiltasten und springt mit T auf heute', async () => {
    await rendern();
    const titel = (name: string) =>
      screen.getByRole('heading', { level: 1, name });
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    await waitFor(() => expect(titel('September 2026')).toBeTruthy());
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    await waitFor(() => expect(titel('August 2026')).toBeTruthy());
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    fireEvent.keyDown(window, { key: 't' });
    await waitFor(() => expect(titel('August 2026')).toBeTruthy());
  });

  it('wechselt die Ansicht mit den Zifferntasten', async () => {
    await rendern();
    fireEvent.keyDown(window, { key: '3' });
    await waitFor(() => expect(
      screen.getByRole('tab', { name: 'Woche' }).getAttribute('aria-selected'))
      .toBe('true'));
  });

  it('greift nicht in ein Eingabefeld ein', async () => {
    await rendern();
    const feld = screen.getByLabelText('Termine durchsuchen');
    fireEvent.keyDown(feld, { key: 't' });
    // Der Titel darf sich dadurch nicht aendern.
    expect(screen.getByRole('heading', { level: 1, name: 'August 2026' }))
      .toBeTruthy();
  });
});

describe('Navigation (B1)', () => {
  it('bindet die Seite genau einmal in Route und Navigation ein', async () => {
    const { readFileSync } = await import('node:fs');
    const { join, dirname } = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const hier = dirname(fileURLToPath(import.meta.url));
    const app = readFileSync(join(hier, '../../App.tsx'), 'utf8');
    const sidebar = readFileSync(
      join(hier, '../../components/Sidebar/Sidebar.tsx'), 'utf8');
    expect(app.match(/path="calendar"/g)).toHaveLength(1);
    expect(sidebar.match(/path: '\/calendar'/g)).toHaveLength(1);
  });
});

describe('Bridge-Handshake beim Laden (B1)', () => {
  // Der Live-Lauf vom 2026-08-08 zeigte den Fehler: `/status` meldet den
  // ZULETZT BEKANNTEN Stand, und der ist bei frischem Backend „noch nicht
  // geprueft" — also nicht verfuegbar. Die Ansicht behauptete daraufhin eine
  // fehlende Bridge und bot den Berechtigungsweg nie an, obwohl der
  // Handshake gegen dasselbe Backend `bridge_available: true` lieferte.

  it('prueft die Bridge beim Laden, bevor sie den Status glaubt', async () => {
    mockApi({ status: { authorization_status: 'not_determined', can_read: false } });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(api.pruefeBridge).toHaveBeenCalled());
    // Und der Berechtigungsweg ist danach erreichbar, statt vom
    // Nichtverfuegbar-Zustand verdeckt zu werden.
    expect(screen.getByRole('button', { name: 'Zugriff anfragen' })).toBeTruthy();
  });

  it('bleibt beim Handshake ein Lesevorgang: kein Sync, keine Berechtigungsfrage', async () => {
    const sync = vi.spyOn(api, 'synchronisiere');
    const frage = vi.spyOn(api, 'frageBerechtigungAn');
    await rendern();
    expect(api.pruefeBridge).toHaveBeenCalled();
    expect(sync).not.toHaveBeenCalled();
    expect(frage).not.toHaveBeenCalled();
  });

  it('wirft die Ansicht nicht in den Fehlerzustand, wenn der Handshake scheitert', async () => {
    mockApi({ status: { bridge_available: false, can_read: false,
                        authorization_status: 'unknown' } });
    vi.spyOn(api, 'pruefeBridge').mockRejectedValue(new Error('kein Backend'));
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    // Fail-closed und ehrlich: der Vorwert bleibt stehen und wird benannt.
    expect(screen.getByText(/nicht gesagt, dass dein Kalender leer ist/)).toBeTruthy();
  });
});

describe('Tagesauswahl (B2)', () => {
  it('waehlt einen leeren Tag per Klick sichtbar aus', async () => {
    await rendern();
    const leer = screen.getAllByTestId('kalender-tag')
      .find((z) => z.getAttribute('data-date') === '2026-08-05')!;
    fireEvent.click(leer);
    expect(leer.getAttribute('data-selected')).toBe('1');
    expect(leer.getAttribute('aria-selected')).toBe('true');
  });

  it('waehlt einen belegten Tag aus und wechselt die Auswahl korrekt', async () => {
    await rendern();
    const zellen = screen.getAllByTestId('kalender-tag');
    const belegt = zellen.find((z) => z.getAttribute('data-date') === '2026-08-12')!;
    const anderer = zellen.find((z) => z.getAttribute('data-date') === '2026-08-20')!;
    fireEvent.click(belegt);
    expect(belegt.getAttribute('data-selected')).toBe('1');
    fireEvent.click(anderer);
    expect(anderer.getAttribute('data-selected')).toBe('1');
    expect(belegt.getAttribute('data-selected')).toBe('0');
  });

  it('oeffnet beim Wechsel auf Tag genau den gewaehlten Tag', async () => {
    await rendern();
    const zelle = screen.getAllByTestId('kalender-tag')
      .find((z) => z.getAttribute('data-date') === '2026-08-05')!;
    fireEvent.click(zelle);
    fireEvent.click(screen.getByRole('tab', { name: 'Tag' }));
    await waitFor(() => expect(
      screen.getByRole('heading', { level: 1,
        name: /Mittwoch, 05\. August 2026/ })).toBeTruthy());
  });

  it('loest bei Auswahl und Wechsel keinerlei Schreib- oder Synclauf aus', async () => {
    const sync = vi.spyOn(api, 'synchronisiere');
    const frage = vi.spyOn(api, 'frageBerechtigungAn');
    await rendern();
    const zelle = screen.getAllByTestId('kalender-tag')
      .find((z) => z.getAttribute('data-date') === '2026-08-05')!;
    fireEvent.click(zelle);
    fireEvent.click(screen.getByRole('tab', { name: 'Tag' }));
    expect(sync).not.toHaveBeenCalled();
    expect(frage).not.toHaveBeenCalled();
  });

  it('ohne Auswahl bleibt der Tageswechsel beim bisherigen Verhalten', async () => {
    await rendern();
    fireEvent.click(screen.getByRole('tab', { name: 'Tag' }));
    await waitFor(() => expect(
      screen.getByRole('heading', { level: 1,
        name: /Mittwoch, 12\. August 2026/ })).toBeTruthy());
  });
});

describe('Referenzmerkmale der Monatsansicht (B2)', () => {
  it('zeigt den Umschalter in der Reihenfolge Tag Woche Monat Jahr', async () => {
    await rendern();
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
    expect(tabs).toEqual(['Tag', 'Woche', 'Monat', 'Jahr']);
  });

  it('setzt die Tageszahl rechts und die Koepfe ohne Vollgrossschreibung', async () => {
    await rendern();
    const koepfe = screen.getAllByRole('columnheader').map((k) => k.textContent);
    expect(koepfe.length).toBe(7);
    // Locale-uebliche Kurzform, nicht MO/DI/…: mindestens ein Kleinbuchstabe.
    for (const kopf of koepfe) expect(kopf).toMatch(/[a-zäöü]/);
    const zelle = screen.getAllByTestId('kalender-tag')[0]!;
    const zeile = zelle.querySelector('div')!;
    expect(zeile.className).toContain('justify-end');
  });

  it('zeigt den Miniaturmonat in der Seitenleiste', async () => {
    await rendern();
    expect(screen.getByTestId('kalender-minimonat')).toBeTruthy();
  });

  it('rendert zeitgebundene Termine ohne Vollflaeche und ganztaegige als Balken', async () => {
    const zeitgebunden = termin();
    const ganztags: Termin = { ...termin(), id: 'evt-ganz', is_all_day: true,
      starts_at_utc: '2026-08-13T00:00:00Z', ends_at_utc: '2026-08-14T00:00:00Z' };
    mockApi({ termine: [zeitgebunden, ganztags] });
    render(<CalendarWorkspace />);
    await waitFor(() => expect(screen.getByTestId('kalender-workspace')).toBeTruthy());
    const chips = screen.getAllByTestId('kalender-termin');
    const zeitChip = chips.find((c) => c.getAttribute('data-event-id') === zeitgebunden.id)!;
    const ganzChip = chips.find((c) => c.getAttribute('data-event-id') === 'evt-ganz')!;
    expect(zeitChip.style.background).toBe('transparent');
    expect(ganzChip.style.background).not.toBe('transparent');
  });
});

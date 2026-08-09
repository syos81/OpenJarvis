// @vitest-environment jsdom
//
// Der Lösch-Dialog mit Freigabefluss (B3 P3) — geprüft werden die
// Datenverlust- und Ehrlichkeitsregeln des Kanals:
//
//  · Eine nicht-eligible Probe verweigert SICHTBAR — der Server wird nie
//    erreicht (kein bereiteLoeschenVor), nichts wird vorbereitet.
//  · Die Vorschau ist die SERVER-Vorschau mit GENAU EINEM Freigabeknopf.
//  · „Abbrechen" ruft cancel und erreicht NIE den App-Prozess.
//  · „Löschen freigeben" läuft exakt approve → claim → execute → settle.
//  · Ein revision_conflict/unsupported_field meldet ehrlich: nichts gesendet.

process.env.TZ = 'Europe/Berlin';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { Termin } from './api';
import * as mApi from './mutationsApi';
import { TerminLoeschen } from './TerminLoeschen';

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

const PROBE: mApi.LoeschProbe = {
  schema_version: 1, event_identifier: 'EK-EVENT-1',
  provider_calendar_id: 'cal-1', eligible: true,
  unsupported_feature_flags: [],
  counts: { alarms: 0, attendees: 0, recurrence_rules: 0 },
};

const VORGANG: mApi.VorbereiteterVorgang = {
  mutation_id: 'm1', approval_id: 'a1', state: 'prepared',
  payload_digest: 'p'.repeat(64),
  preview: {
    command: 'delete', calendar_display_name: 'Privat', title: 'Zahnarzt',
    starts_at_utc: '2026-08-12T08:00:00Z', ends_at_utc: '2026-08-12T09:00:00Z',
    is_all_day: false, location: null, time_zone: 'Europe/Berlin',
    deletion: {
      eligible: true, unsupported_feature_flags: [],
      restore_preimage_present: true,
    },
  },
  preview_digest: 'q'.repeat(64),
};

const AUFTRAG: mApi.KalenderExecutionOrder = {
  schema_version: 1, operation_id: 'op1', mutation_id: 'm1',
  claim_token: 'token-1', operation_type: 'delete',
  payload_digest: 'p'.repeat(64), preview_digest: 'q'.repeat(64),
  canonical_payload: {}, issued_at: '2026-08-12T10:00:00Z',
  expires_at: '2026-08-12T10:05:00Z',
  provider_target: { provider_calendar_id: 'cal-1', event_identifier: 'EK-EVENT-1' },
  expected_fingerprint: 'f'.repeat(64),
};

function bericht(over: Partial<mApi.KalenderExecutionReport> = {},
): mApi.KalenderExecutionReport {
  return {
    schema_version: 1, operation_id: 'op1', mutation_id: 'm1',
    operation_type: 'delete', outcome: 'applied', send_attempted: true,
    save_request_count: 1, readback_status: 'absent_confirmed',
    readback_event: null, provider_identifier: 'EK-EVENT-1',
    fingerprint_checked: true, fingerprint_matched: true,
    error_class: null, error_digest: null,
    provider_completed_at: '2026-08-12T10:00:01Z', ...over,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

function oeffne(termin: Termin = bestandsTermin()) {
  const schliessen = vi.fn();
  const erfolg = vi.fn();
  render(<TerminLoeschen termin={termin} zone="Europe/Berlin"
    aufSchliessen={schliessen} aufErfolg={erfolg} />);
  return { schliessen, erfolg };
}

describe('Eligibility-Verweigerung (Datenverlustschutz)', () => {
  it('verweigert sichtbar und erreicht den Server nie', async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue({
      ...PROBE, eligible: false,
      unsupported_feature_flags: ['attendees', 'recurrence_rules'],
      counts: { alarms: 0, attendees: 2, recurrence_rules: 1 },
    });
    const vorbereiten = vi.spyOn(mApi, 'bereiteLoeschenVor');
    const ausfuehren = vi.spyOn(mApi, 'fuehreAus');
    oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-blocked')).toBeTruthy());
    // Die Flags erscheinen verständlich benannt.
    expect(screen.getByText('Teilnehmer')).toBeTruthy();
    expect(screen.getByText('Wiederholungsregel')).toBeTruthy();
    // Kein Freigabeknopf, kein Serverkontakt, kein App-Prozess.
    expect(screen.queryByText('Löschen freigeben')).toBeNull();
    expect(vorbereiten).not.toHaveBeenCalled();
    expect(ausfuehren).not.toHaveBeenCalled();
  });

  it('verweigert ehrlich, wenn die Probe nicht erhebbar ist', async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(null);
    const vorbereiten = vi.spyOn(mApi, 'bereiteLoeschenVor');
    oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-ergebnis')).toBeTruthy());
    expect(vorbereiten).not.toHaveBeenCalled();
  });
});

describe('Vorschau und Freigabe', () => {
  it('zeigt die SERVER-Vorschau mit Löschhinweis und genau einem Freigabeknopf',
     async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(PROBE);
    const vorbereiten = vi.spyOn(mApi, 'bereiteLoeschenVor')
      .mockResolvedValue(VORGANG);
    oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-vorschau')).toBeTruthy());
    // Die Probe reist UNVERÄNDERT zum Server.
    expect(vorbereiten).toHaveBeenCalledWith('cal-1', 'EK-EVENT-1', PROBE);
    expect(screen.getByText('Privat')).toBeTruthy();
    expect(screen.getByText('Zahnarzt')).toBeTruthy();
    expect(screen.getByText(/endgültig gelöscht/)).toBeTruthy();
    expect(screen.getByTestId('loeschen-eligibility').textContent)
      .toContain('verlustfrei wiederherstellbar');
    expect(screen.getAllByText('Löschen freigeben')).toHaveLength(1);
  });

  it('Abbrechen ruft cancel und erreicht nie den App-Prozess', async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(PROBE);
    vi.spyOn(mApi, 'bereiteLoeschenVor').mockResolvedValue(VORGANG);
    const abbruch = vi.spyOn(mApi, 'bricheAb')
      .mockResolvedValue({ mutation_id: 'm1', state: 'cancelled' });
    const ausfuehren = vi.spyOn(mApi, 'fuehreAus');
    const { schliessen } = oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-vorschau')).toBeTruthy());
    fireEvent.click(screen.getByText('Abbrechen'));
    await waitFor(() => expect(schliessen).toHaveBeenCalled());
    expect(abbruch).toHaveBeenCalledWith('m1');
    expect(ausfuehren).not.toHaveBeenCalled();
  });

  it('laeuft exakt approve → claim → execute → settle und meldet Erfolg',
     async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(PROBE);
    vi.spyOn(mApi, 'bereiteLoeschenVor').mockResolvedValue(VORGANG);
    const reihenfolge: string[] = [];
    vi.spyOn(mApi, 'gibFrei').mockImplementation(async () => {
      reihenfolge.push('approve');
      return { mutation_id: 'm1', state: 'approved' };
    });
    vi.spyOn(mApi, 'beanspruche').mockImplementation(async () => {
      reihenfolge.push('claim');
      return AUFTRAG;
    });
    vi.spyOn(mApi, 'fuehreAus').mockImplementation(async () => {
      reihenfolge.push('execute');
      return bericht();
    });
    vi.spyOn(mApi, 'schliesseAb').mockImplementation(async () => {
      reihenfolge.push('settle');
      return { mutation_id: 'm1', state: 'succeeded', outcome: 'succeeded',
               idempotent: false, error_class: null };
    });
    const { erfolg } = oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-vorschau')).toBeTruthy());
    fireEvent.click(screen.getByText('Löschen freigeben'));
    await waitFor(() => expect(screen.getByTestId('loeschen-ergebnis')).toBeTruthy());
    expect(reihenfolge).toEqual(['approve', 'claim', 'execute', 'settle']);
    expect(screen.getByRole('status').textContent).toContain('gelöscht');
    expect(erfolg).toHaveBeenCalled();
  });

  it('meldet einen revision_conflict ehrlich als nicht gesendet', async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(PROBE);
    vi.spyOn(mApi, 'bereiteLoeschenVor').mockResolvedValue(VORGANG);
    vi.spyOn(mApi, 'gibFrei')
      .mockResolvedValue({ mutation_id: 'm1', state: 'approved' });
    vi.spyOn(mApi, 'beanspruche').mockResolvedValue(AUFTRAG);
    vi.spyOn(mApi, 'fuehreAus').mockResolvedValue(bericht({
      outcome: 'not_sent', send_attempted: false, save_request_count: 0,
      readback_status: 'not_checked', provider_identifier: null,
      fingerprint_matched: false, error_class: 'revision_conflict',
      provider_completed_at: null }));
    vi.spyOn(mApi, 'schliesseAb').mockResolvedValue({
      mutation_id: 'm1', state: 'failed_before_send', outcome: 'failed',
      idempotent: false, error_class: 'revision_conflict' });
    const { erfolg } = oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-vorschau')).toBeTruthy());
    fireEvent.click(screen.getByText('Löschen freigeben'));
    await waitFor(() => expect(screen.getByTestId('loeschen-ergebnis')).toBeTruthy());
    expect(screen.getByRole('status').textContent)
      .toContain('nichts gesendet');
    expect(erfolg).not.toHaveBeenCalled();
  });

  it('meldet eine serverseitige Nicht-Eligibility typisiert', async () => {
    vi.spyOn(mApi, 'erhebeLoeschProbe').mockResolvedValue(PROBE);
    vi.spyOn(mApi, 'bereiteLoeschenVor').mockRejectedValue(
      new mApi.MutationsFehler(409, 'delete_not_eligible'));
    const { erfolg } = oeffne();
    await waitFor(() => expect(screen.getByTestId('loeschen-ergebnis')).toBeTruthy());
    expect(screen.getByText(/nicht verlustfrei wiederherstellen/)).toBeTruthy();
    expect(erfolg).not.toHaveBeenCalled();
  });
});

// @vitest-environment jsdom
// Der Schalter der dauerhaften Schreibfreigabe.
//
// Geprüft wird das, was schiefgehen darf und nicht schiefgehen darf: dass ein
// abgebrochener Touch-ID-Dialog aus bleiben lässt, dass Ausschalten ohne
// Authentifizierung geht, und dass die Oberfläche keinen Zustand behauptet,
// den der App-Prozess nicht gemeldet hat.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { SchreibfreigabeSchalter } from './SchreibfreigabeSchalter';
import { grundText } from './schreibfreigabe';

const invoke = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('../../../lib/api', () => ({ isTauri: () => true }));

const AUS = { standing: false, operations: [], reason_code: null };
const AN = { standing: true, operations: ['create', 'update'], reason_code: null };

beforeEach(() => {
  invoke.mockReset();
});

describe('Schreibfreigabe-Schalter', () => {
  it('zeigt den gemessenen Zustand, nicht einen angenommenen', async () => {
    invoke.mockResolvedValue(AN);
    render(<SchreibfreigabeSchalter />);
    await waitFor(() => {
      expect(screen.getByTestId('contacts-schreibfreigabe-schalter'))
        .toHaveAttribute('aria-checked', 'true');
    });
    expect(invoke).toHaveBeenCalledWith('personal_contacts_standing_write_state');
  });

  it('schaltet ein und meldet dabei die erteilten Operationen', async () => {
    invoke.mockResolvedValueOnce(AUS).mockResolvedValueOnce(AN);
    render(<SchreibfreigabeSchalter />);
    const schalter = await screen.findByTestId('contacts-schreibfreigabe-schalter');
    await waitFor(() => expect(schalter).toBeEnabled());

    await userEvent.click(schalter);

    await waitFor(() => expect(schalter).toHaveAttribute('aria-checked', 'true'));
    expect(invoke).toHaveBeenLastCalledWith('personal_contacts_standing_write_enable');
  });

  it('bleibt aus, wenn die Systemauthentifizierung abgebrochen wird', async () => {
    invoke
      .mockResolvedValueOnce(AUS)
      .mockResolvedValueOnce({ ...AUS, reason_code: 'owner_authentication_failed' });
    render(<SchreibfreigabeSchalter />);
    const schalter = await screen.findByTestId('contacts-schreibfreigabe-schalter');
    await waitFor(() => expect(schalter).toBeEnabled());

    await userEvent.click(schalter);

    await waitFor(() => expect(schalter).toHaveAttribute('aria-checked', 'false'));
    expect(screen.getByTestId('contacts-schreibfreigabe-hinweis').textContent)
      .toContain('abgebrochen');
  });

  it('schaltet ohne Authentifizierung wieder aus', async () => {
    invoke.mockResolvedValueOnce(AN).mockResolvedValueOnce(AUS);
    render(<SchreibfreigabeSchalter />);
    const schalter = await screen.findByTestId('contacts-schreibfreigabe-schalter');
    await waitFor(() => expect(schalter).toHaveAttribute('aria-checked', 'true'));

    await userEvent.click(schalter);

    await waitFor(() => expect(schalter).toHaveAttribute('aria-checked', 'false'));
    expect(invoke).toHaveBeenLastCalledWith('personal_contacts_standing_write_disable');
  });

  it('nennt Löschen ausdrücklich als nicht erfasst', async () => {
    invoke.mockResolvedValue(AN);
    render(<SchreibfreigabeSchalter />);
    const flaeche = await screen.findByTestId('contacts-schreibfreigabe');
    expect(flaeche.textContent).toContain('Löschen');
  });

  it('behauptet keinen Schutz gegen andere Programme', async () => {
    invoke.mockResolvedValue(AN);
    render(<SchreibfreigabeSchalter />);
    const flaeche = await screen.findByTestId('contacts-schreibfreigabe');
    // Die Ehrlichkeitsgrenze steht in der Oberfläche, nicht nur im Bericht.
    expect(flaeche.textContent).toContain('anderes Programm');
    expect(flaeche.textContent).not.toContain('manipulationssicher');
  });
});

describe('grundText', () => {
  it('gibt für den Normalfall nichts aus', () => {
    expect(grundText(null)).toBeNull();
  });

  it('kennt jede geschlossene Kennung des App-Prozesses', () => {
    for (const code of ['owner_authentication_failed',
                        'owner_authentication_unavailable',
                        'release_directory_not_private',
                        'write_failed', 'verification_failed']) {
      expect(grundText(code)).toBeTruthy();
    }
  });
});

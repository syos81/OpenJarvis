// @vitest-environment jsdom
// Der sichtbare Stand des Kontingents.
//
// Geprüft wird das, was an einer Anzeige schiefgehen kann: dass sie einen Satz
// erfindet, dass sie eine Zahl zeigt, wo es keine gibt, oder dass sie einen
// alten Stand stehen lässt, nachdem sich der Stand geändert hat.

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

import { Kontingentanzeige } from './Kontingentanzeige';

const getWriteQuota = vi.fn();

vi.mock('../api', () => ({ getWriteQuota: () => getWriteQuota() }));

const STAND = {
  active: true, used: 3, limit: 10, remaining: 7, exhausted: false,
  text: '7 von 10 Schreibvorgängen verfügbar',
};

beforeEach(() => {
  getWriteQuota.mockReset();
});

describe('Kontingentanzeige', () => {
  it('zeigt den Satz des Kerns, ohne ihn nachzubauen', async () => {
    getWriteQuota.mockResolvedValue(STAND);
    render(<Kontingentanzeige />);
    expect(await screen.findByTestId('contacts-kontingent'))
      .toHaveTextContent('7 von 10 Schreibvorgängen verfügbar');
  });

  it('zeigt den erschöpften Stand wörtlich', async () => {
    getWriteQuota.mockResolvedValue({
      active: true, used: 10, limit: 10, remaining: 0, exhausted: true,
      text: '10 von 10 verwendet – erneut freigeben erforderlich',
    });
    render(<Kontingentanzeige />);
    expect(await screen.findByTestId('contacts-kontingent'))
      .toHaveTextContent('10 von 10 verwendet – erneut freigeben erforderlich');
  });

  it('schweigt ohne Dauerfreigabe', async () => {
    // Ohne Aktivierung gibt es nichts zu zählen; die Grenze eines Vorgangs
    // ist dann die Zeit. Eine Zahl an dieser Stelle wäre schlicht falsch.
    getWriteQuota.mockResolvedValue({ ...STAND, active: false });
    render(<Kontingentanzeige />);
    await waitFor(() => expect(getWriteQuota).toHaveBeenCalled());
    expect(screen.queryByTestId('contacts-kontingent')).toBeNull();
  });

  it('rät nichts, wenn der Abruf scheitert', async () => {
    // Eine geratene Zahl wäre schlimmer als gar keine: Der Eigentümer plant
    // danach, wie viele Änderungen er noch machen kann.
    getWriteQuota.mockRejectedValue(new Error('offline'));
    render(<Kontingentanzeige />);
    await waitFor(() => expect(getWriteQuota).toHaveBeenCalled());
    expect(screen.queryByTestId('contacts-kontingent')).toBeNull();
  });

  it('liest neu, wenn sich der Schlüssel ändert', async () => {
    getWriteQuota
      .mockResolvedValueOnce(STAND)
      .mockResolvedValueOnce({
        active: true, used: 4, limit: 10, remaining: 6, exhausted: false,
        text: '6 von 10 Schreibvorgängen verfügbar',
      });
    const { rerender } = render(<Kontingentanzeige schluessel="approved:0" />);
    expect(await screen.findByTestId('contacts-kontingent'))
      .toHaveTextContent('7 von 10');

    rerender(<Kontingentanzeige schluessel="succeeded:1" />);

    await waitFor(() => {
      expect(screen.getByTestId('contacts-kontingent'))
        .toHaveTextContent('6 von 10 Schreibvorgängen verfügbar');
    });
  });

  it('liest nicht erneut, solange der Schlüssel gleich bleibt', async () => {
    // Kein Zeitgeber: Der Stand ändert sich nur durch eine Handlung des
    // Eigentümers, und der Aufrufer weiss, wann er eine ausgelöst hat.
    getWriteQuota.mockResolvedValue(STAND);
    const { rerender } = render(<Kontingentanzeige schluessel="approved:0" />);
    await screen.findByTestId('contacts-kontingent');

    rerender(<Kontingentanzeige schluessel="approved:0" />);

    await waitFor(() => expect(getWriteQuota).toHaveBeenCalledTimes(1));
  });
});

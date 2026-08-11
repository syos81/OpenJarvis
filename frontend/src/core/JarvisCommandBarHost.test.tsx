// @vitest-environment jsdom
//
// Öffnen und Schliessen der Command Bar — die Tastatur ist hier die
// Erfolgsbedingung, also braucht diese Datei ein DOM und fordert es per
// Docblock an (Repo-Vorgabe ist `node`, jsdom ist die Ausnahme).
//
// Geprüft wird der Host, nicht die App: so hängt der Nachweis nicht an
// Modell-Abrufen, Analytics oder Health-Polling.

import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { JarvisCommandBarHost } from './JarvisCommandBarHost';
import { JarvisCommandBar } from './JarvisCommandBar';
import { LeseQuelleNichtErreichbar } from './readPort';

const zeige = (route = '/calendar') =>
  render(
    <MemoryRouter initialEntries={[route]}>
      <JarvisCommandBarHost />
    </MemoryRouter>,
  );

const cmdK = () => fireEvent.keyDown(window, { key: 'k', metaKey: true });

describe('Command Bar', () => {
  it('ist geschlossen, bis jemand sie ruft', () => {
    zeige();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('öffnet mit Cmd+K und schliesst mit Esc', () => {
    zeige();
    cmdK();
    expect(screen.getByRole('dialog', { name: 'Jarvis Command Bar' })).toBeTruthy();

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('führt status lokal aus und zeigt Core und Ansicht', () => {
    zeige('/calendar');
    cmdK();

    const feld = screen.getByLabelText('Befehl');
    fireEvent.change(feld, { target: { value: 'status' } });
    fireEvent.keyDown(feld, { key: 'Enter' });

    const ergebnis = screen.getByTestId('jarvis-core-result');
    expect(ergebnis.getAttribute('data-kind')).toBe('status');
    expect(ergebnis.textContent).toContain('Jarvis Core v0 aktiv');
    expect(ergebnis.textContent).toContain('/calendar');
  });

  it('beantwortet eine unbekannte Eingabe sichtbar statt still', () => {
    zeige();
    cmdK();

    const feld = screen.getByLabelText('Befehl');
    fireEvent.change(feld, { target: { value: 'mach mal was' } });
    fireEvent.keyDown(feld, { key: 'Enter' });

    const ergebnis = screen.getByTestId('jarvis-core-result');
    expect(ergebnis.getAttribute('data-kind')).toBe('unknown');
    expect(ergebnis.textContent).toContain('mach mal was');
  });
});

// ── B: Lese-Integration ueber die echte Bar (Fixtures, kein Backend) ──────

describe('Command Bar: Lesekommandos', () => {
  const port = {
    async sucheKontakte() {
      return {
        treffer: [{ id: 'k1', name: 'Anna Beispiel', organisation: null,
                    emailAnzahl: 1, telefonAnzahl: 0 }],
        weitereVorhanden: false,
      };
    },
    async ladeTermine() {
      return [{ id: 'e1', titel: 'Testtermin',
                startUtc: '2026-08-11T08:00:00Z', endeUtc: '2026-08-11T09:00:00Z',
                ganztaegig: false, kalender: 'Privat' }];
    },
  };

  const tippen = (text: string) => {
    const feld = screen.getByRole('textbox');
    fireEvent.change(feld, { target: { value: text } });
    fireEvent.keyDown(feld, { key: 'Enter' });
  };

  it('zeigt echte Kontakttreffer ueber den injizierten Port', async () => {
    render(<JarvisCommandBar context={{}} onClose={() => {}} readPort={port} />);
    tippen('kontakt Anna');
    await waitFor(() => expect(screen.getByText(/Anna Beispiel/)).toBeTruthy());
  });

  it('zeigt Termine ueber den injizierten Port', async () => {
    render(<JarvisCommandBar context={{}} onClose={() => {}} readPort={port} />);
    tippen('termine 2026-08-11');
    await waitFor(() => expect(screen.getByText(/Testtermin/)).toBeTruthy());
  });

  it('meldet ein nicht erreichbares Backend sichtbar — ohne Absturz', async () => {
    const tot = {
      async sucheKontakte(): Promise<never> {
        throw new LeseQuelleNichtErreichbar('kontakte');
      },
      async ladeTermine(): Promise<never> {
        throw new LeseQuelleNichtErreichbar('termine');
      },
    };
    render(<JarvisCommandBar context={{}} onClose={() => {}} readPort={tot} />);
    tippen('kontakt Anna');
    await waitFor(() => expect(screen.getByText(/nicht verfügbar/)).toBeTruthy());
    // Und die rein lokalen Befehle funktionieren danach weiter.
    tippen('status');
    await waitFor(() => expect(screen.getByText(/Jarvis Core v0 aktiv/)).toBeTruthy());
  });
});

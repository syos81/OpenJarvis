// @vitest-environment jsdom
//
// Öffnen und Schliessen der Command Bar — die Tastatur ist hier die
// Erfolgsbedingung, also braucht diese Datei ein DOM und fordert es per
// Docblock an (Repo-Vorgabe ist `node`, jsdom ist die Ausnahme).
//
// Geprüft wird der Host, nicht die App: so hängt der Nachweis nicht an
// Modell-Abrufen, Analytics oder Health-Polling.

import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { JarvisCommandBarHost } from './JarvisCommandBarHost';

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

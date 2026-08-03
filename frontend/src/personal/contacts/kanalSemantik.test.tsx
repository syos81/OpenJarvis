// @vitest-environment jsdom
//
// Kanalsemantik im Frontend und Fensterung ohne Layout.
//
// Zwei Härtungen dieses Stands werden hier festgehalten:
//
// 1. Das Frontend kann eine abgeschaltete Fähigkeit **nicht** übersteuern.
//    Es liest die Serverantwort und wendet dieselbe Konjunktion an wie der
//    Kern; ein widersprüchlicher Handshake gilt als „nein".
// 2. Die Liste fenstert auch dann, wenn keine Höhe gemessen werden kann.
//    Vorher entstand in jsdom — und im ersten Browser-Frame — der volle
//    DOM; bei 10.000 Kontakten ein Baum, den niemand sieht. Dieselbe
//    Verschwendung machte die Fixture-Tests unter Last langsam genug, um
//    an RTLs Ein-Sekunden-Fenster zu reissen.
//
// Kontaktfrei, ohne Netz: alle Fähigkeitssätze sind Attrappen.

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { PHASE_A_KANALTEXT, kanalErlaubt } from './api';
import type { AppChannelCapabilities } from './api';
import { ANNAHME_VIEWPORT, ContactsListPane } from './list/ContactsListPane';
import { syntheticSummaries } from './data/fixtures';
import { sortiereKontakte } from './data/sortierung';

const AUS: AppChannelCapabilities = {
  schema_version: 2,
  channel: 'app_process',
  channel_mode: 'disabled',
  create_supported: false,
  update_supported: false,
  delete_supported: false,
  provider_write_enabled: false,
  architecture: 'x86_64',
  app_version: '1.0.1',
  native_bridge_version: '0',
};

describe('Kanalsemantik: das Frontend schaltet nichts frei', () => {
  it('verweigert im Releasezustand jede Operation', () => {
    for (const op of ['create', 'update', 'delete'] as const) {
      expect(kanalErlaubt(AUS, op), op).toBe(false);
    }
  });

  it('verweigert ohne Antwort — fail-closed statt „wahrscheinlich ja"', () => {
    expect(kanalErlaubt(null, 'create')).toBe(false);
    expect(kanalErlaubt(undefined, 'create')).toBe(false);
  });

  it('erkennt einen widerspruechlichen Handshake als Nein', () => {
    // Genau der Fehlstand, der korrigiert wurde: Operation unterstuetzt,
    // aber niemand darf schreiben.
    const widerspruch = { ...AUS, create_supported: true };
    expect(kanalErlaubt(widerspruch, 'create')).toBe(false);
  });

  it('verweigert bei unbekanntem Kanal oder Modus', () => {
    const fremd = { ...AUS, channel: 'cli_sidecar' } as unknown as
      AppChannelCapabilities;
    expect(kanalErlaubt(fremd, 'create')).toBe(false);
    const modus = { ...AUS, channel_mode: 'native' } as unknown as
      AppChannelCapabilities;
    expect(kanalErlaubt(modus, 'create')).toBe(false);
  });

  it('laesst nur die tatsaechlich gemeldete Operation durch', () => {
    const fake: AppChannelCapabilities = {
      ...AUS, channel_mode: 'fake_debug',
      provider_write_enabled: true, create_supported: true,
    };
    expect(kanalErlaubt(fake, 'create')).toBe(true);
    expect(kanalErlaubt(fake, 'update')).toBe(false);
    expect(kanalErlaubt(fake, 'delete')).toBe(false);
  });

  it('nennt den Phase-A-Zustand woertlich', () => {
    expect(PHASE_A_KANALTEXT)
      .toBe('Transport vorbereitet, Provider-Schreiben deaktiviert');
  });
});

describe('Fensterung ohne gemessene Hoehe', () => {
  const gross = sortiereKontakte(syntheticSummaries(2000));

  it('stellt ohne Layout nur einen begrenzten Ausschnitt in den DOM', () => {
    render(<ContactsListPane
      kontakte={gross} auswahlId={null} onAuswahl={() => {}}
      onEnterDetail={() => {}} leerTitel="leer" />);
    const optionen = screen.getAllByRole('option');
    // jsdom meldet `clientHeight === 0`; frueher rendete das alle 2000.
    expect(optionen.length).toBeGreaterThan(0);
    expect(optionen.length).toBeLessThan(200);
  });

  it('meldet trotzdem die volle Menge an die Barrierefreiheit', () => {
    render(<ContactsListPane
      kontakte={gross} auswahlId={null} onAuswahl={() => {}}
      onEnterDetail={() => {}} leerTitel="leer" />);
    expect(screen.getAllByRole('option')[0])
      .toHaveAttribute('aria-setsize', '2000');
  });

  it('deckt mit der Annahme mehr als jeden ueblichen Bildschirm ab', () => {
    // 2000 Pixel sind mehr als die hoehe jedes gaengigen Fensters — vor der
    // ersten Messung fehlt damit nichts Sichtbares.
    expect(ANNAHME_VIEWPORT).toBeGreaterThanOrEqual(1200);
  });
});

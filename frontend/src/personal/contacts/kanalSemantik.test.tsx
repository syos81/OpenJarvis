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
  schema_version: 3,
  channel: 'app_process',
  channel_mode: 'disabled',
  native_create_available: true,
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

  it('verweigert den nativen Modus ohne Schreibrecht', () => {
    // `native_create` ohne `provider_write_enabled` ist ein Widerspruch:
    // Der Modus behauptet einen Schreibkanal, das Flag verneint ihn.
    const halb = { ...AUS, channel_mode: 'native_create' as const };
    expect(kanalErlaubt(halb, 'create')).toBe(false);
  });

  it('laesst den nativen Modus mit Freigabe genau fuer create durch', () => {
    const nativ: AppChannelCapabilities = {
      ...AUS, channel_mode: 'native_create',
      provider_write_enabled: true, create_supported: true,
    };
    expect(kanalErlaubt(nativ, 'create')).toBe(true);
    expect(kanalErlaubt(nativ, 'update')).toBe(false);
    expect(kanalErlaubt(nativ, 'delete')).toBe(false);
  });

  it('verweigert bei unbekanntem Kanal oder Modus', () => {
    const fremd = { ...AUS, channel: 'cli_sidecar' } as unknown as
      AppChannelCapabilities;
    expect(kanalErlaubt(fremd, 'create')).toBe(false);
    const modus = { ...AUS, channel_mode: 'irgendwas' } as unknown as
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

describe('Löschbestätigung (R2, DEC-046)', () => {
  it('reicht die Bestätigung nur für delete weiter', async () => {
    const gesehen: Array<[string, boolean]> = [];
    const quelle = {
      execute: async (id: string, confirmDelete = false) => {
        gesehen.push([id, confirmDelete]);
      },
    };
    await quelle.execute('m-update', false);
    await quelle.execute('m-delete', true);
    expect(gesehen).toEqual([['m-update', false], ['m-delete', true]]);
  });

  it('macht etikettierte Listen in der Vorschau lesbar', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
    // `String(wert)` ergab bei Listen `[object Object]` — genau das, was der
    // Mensch vor der Freigabe nicht pruefen kann.
    expect(quelle).toContain('function lesbar(');
    expect(quelle).toContain('{lesbar(c.previous)}');
    expect(quelle).not.toContain("String(c.planned ?? '—')");
  });

  it('laesst den Kanalhinweis dem tatsaechlichen Zustand folgen', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
    // Fest verdrahtet war er richtig, solange der Kanal konstant zu war;
    // seit der Freigabe behauptete er das Gegenteil dessen, was gleich
    // passiert.
    expect(quelle).toContain('function KanalHinweis({ caps }');
    expect(quelle).toContain('Provider-Schreiben ist zeitlich begrenzt freigegeben.');
    expect(quelle).toContain('caps.create_supported || caps.update_supported');
  });

  it('nennt die Unumkehrbarkeit im Bestätigungstext', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
    const block = quelle.split('data-testid="delete-bestaetigung"')[1]
      .slice(0, 600);
    expect(block).toContain('löschen');
    expect(block).toContain('nicht rückgängig');
  });

  it('sperrt den Ausführungsknopf, solange nicht bestätigt ist', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
    expect(quelle).toContain("(m.command === 'delete' && !bestaetigt)");
  });
});

describe('Neuanlage: etikettierte Listen', () => {
  it('bietet E-Mail und Telefon mit dem v1-Labelvorrat an', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(), 'src/personal/contacts/editor/dialogs.tsx'),
      'utf8');
    const block = quelle.split('const ANLAGE_LISTEN')[1].slice(0, 400);
    expect(block).toContain("key: 'emails'");
    expect(block).toContain("key: 'phones'");
    // Genau der Vorrat des Feldvertrags v1 — nichts darüber hinaus.
    expect(block).toContain("['home', 'work', 'other']");
    expect(block).toContain("['mobile', 'home', 'work', 'main', 'other']");
  });

  it('zaehlt leere Zeilen nicht als Eingabe', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(), 'src/personal/contacts/editor/dialogs.tsx'),
      'utf8');
    // Sonst haenge der Digest daran, ob jemand eine Zeile geoeffnet hat.
    expect(quelle).toContain("filter((e) => e.value.trim() !== '')");
  });
});

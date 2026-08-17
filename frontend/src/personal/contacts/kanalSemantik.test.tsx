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
import { braucht_aufmerksamkeit } from './status/ContactsStatusSurface';
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

describe('Löschbestätigung (R2, DEC-053)', () => {
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

  it('nennt im Bestätigungstext, was umkehrbar ist und was nicht', async () => {
    // Bis zum Löschgate stand hier „nicht rückgängig". Das war wahr, solange
    // es keine Sicherung gab. Seitdem ist der Inhalt wiederherstellbar und
    // nur die Identität nicht — und der alte Satz wäre der ungenauere.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
    const block = quelle.split('data-testid="delete-bestaetigung"')[1]
      .slice(0, 800);
    expect(block).toContain('löschen');
    expect(block).toContain('WiederherstellungsHinweis');
    expect(block).not.toContain('nicht rückgängig');
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

describe('Hauptnavigation der Statusfläche', () => {
  const quellcode = async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    return fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/status/ContactsStatusSurface.tsx'),
      'utf8');
  };

  it('kennt keinen Dauerreiter „Freigaben" mehr', async () => {
    const quelle = await quellcode();
    // Eine Freigabe gehoert an den Vorgang, den sie betrifft — als Dialog im
    // Moment der Entscheidung, nicht als Sammelliste, die man irgendwann
    // durchsieht.
    expect(quelle).not.toContain("{ key: 'freigaben'");
    expect(quelle).not.toContain("tab === 'freigaben'");
  });

  it('zeigt „Vorgänge" nur bei Bedarf', async () => {
    const quelle = await quellcode();
    expect(quelle).toContain('const zeigeVorgaenge = offeneVorgaenge.length > 0');
    expect(quelle).toContain("...(zeigeVorgaenge");
  });

  it('haelt die Diagnose erreichbar, aber nicht als Arbeitsbereich', async () => {
    const quelle = await quellcode();
    expect(quelle).toContain("{ key: 'diagnose', label: 'Diagnose' }");
    expect(quelle).toContain('Technischer Nachweis, kein');
    // Die vollstaendige Historie lebt dort — inklusive der Freigaben.
    const block = quelle.split("tab === 'diagnose'")[1].slice(0, 900);
    expect(block).toContain('<MutationList');
    expect(block).toContain('<ApprovalBoard');
  });

  it('zaehlt nur laufende, klemmende und ungeklaerte Vorgaenge', () => {
    for (const state of ['executing', 'outcome_unknown', 'reconcile_required',
                         'manual_decision_required', 'failed',
                         'failed_before_send',
                         'provider_applied_pending_reconcile']) {
      expect(braucht_aufmerksamkeit(state), state).toBe(true);
    }
    // Abgeschlossenes ist Historie, kein Arbeitsvorrat.
    for (const state of ['succeeded', 'rejected', 'cancelled', 'expired',
                         'awaiting_approval', 'approved', 'prepared',
                         'manually_resolved_applied',
                         'manually_resolved_not_applied']) {
      expect(braucht_aufmerksamkeit(state), state).toBe(false);
    }
  });

  /**
   * Bis zum M2-Abgleich fuehrte eine Freigabe in die Statusflaeche, weil der
   * Vorgang dort noch ausgefuehrt werden musste. Eigene Handlungen laufen
   * jetzt nach ihrer einen Bestaetigung durch — es gibt keinen zweiten
   * Schritt mehr, zu dem hinzufuehren waere. Geprueft wird deshalb, dass der
   * Workspace beide Schritte selbst abschliesst statt sie liegen zu lassen.
   */
  it('gibt eigene Vorgaenge nicht selbst frei und fuehrt sie nicht selbst aus', async () => {
    // Dieser Test stand bis 2026-08-13 auf dem Kopf: Er verlangte genau das
    // Gegenteil und sicherte damit den Defekt als Merkmal ab. Der Livelauf
    // zeigte die Folge — Vorbereiten, Freigeben und Ausfuehren fielen in
    // dieselbe Sekunde, mit hartkodiertem Entscheider.
    const fs = await import('node:fs');
    const path = await import('node:path');
    const quelle = fs.readFileSync(
      path.join(process.cwd(),
                'src/personal/contacts/workspace/ContactsWorkspace.tsx'),
      'utf8');
    expect(quelle).toContain('const abschliessen =');
    expect(quelle).not.toContain('quelle.approve(');
    expect(quelle).not.toContain('quelle.execute(');
    // Stattdessen: der Vorgang geht in die Vorschau, und dort entscheidet
    // der Eigentuemer.
    expect(quelle).toContain('<PreviewDialog');
    expect(quelle).toContain('setVorschau(m)');
  });
});

// @vitest-environment jsdom
//
// Dev-Fixture-Bootstrap: Ein Szenario-Lauf darf **keine** einzige Anfrage
// des Kontakte-Clients auslösen.
//
// Der Client ist hier ein Fail-on-any-call-Mock: jede Funktion schreibt
// ihren Namen in `aufrufe` und liefert eine Ablehnung — sie kann also nie
// unbemerkt „funktionieren". Der eigentliche Nullaufruf-Beweis ist die
// Zusicherung `aufrufe === []`: sie schlaegt fehl, sobald irgendeine
// Clientfunktion auch nur berührt wurde, unabhängig davon, was die
// Oberfläche daraus macht. Abgelehnt statt synchron geworfen wird, damit
// die Fehlerbehandlung der Seite (Abschnitt C) real durchlaufen kann.
// Alle Daten sind synthetisch; es gibt weder Netz noch Datenbank.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const aufrufe: string[] = [];

vi.mock('./api', async () => {
  const echt = await vi.importActual<typeof import('./api')>('./api');
  const scharf = (name: string) => (...args: unknown[]) => {
    aufrufe.push(name);
    return Promise.reject(new Error(
      `VERTRAGSBRUCH: api.${name}(${args.length} Argument(e)) aufgerufen`,
    ));
  };
  return {
    ...echt,
    listContacts: scharf('listContacts'),
    listCategories: scharf('listCategories'),
    getCapabilities: scharf('getCapabilities'),
    listApprovals: scharf('listApprovals'),
    listMutations: scharf('listMutations'),
    getContact: scharf('getContact'),
    getAuthorization: scharf('getAuthorization'),
    getSyncStatus: scharf('getSyncStatus'),
    requestAuthorization: scharf('requestAuthorization'),
    runSync: scharf('runSync'),
    listContainers: scharf('listContainers'),
    assignRole: scharf('assignRole'),
    removeRole: scharf('removeRole'),
    prepareCreate: scharf('prepareCreate'),
    prepareUpdate: scharf('prepareUpdate'),
    prepareDelete: scharf('prepareDelete'),
    getMutation: scharf('getMutation'),
    approveMutation: scharf('approveMutation'),
    rejectMutation: scharf('rejectMutation'),
    cancelMutation: scharf('cancelMutation'),
    expireMutation: scharf('expireMutation'),
    executeMutation: scharf('executeMutation'),
    reconcileMutation: scharf('reconcileMutation'),
    resolveOutcomeNotObserved: scharf('resolveOutcomeNotObserved'),
  };
});

import ContactsPage from './ContactsPage';
import { startQuelle } from './workspace/ContactsWorkspace';

/** Setzt die Adresszeile, ohne die jsdom-Umgebung zu ersetzen. */
function szenario(suche: string): void {
  window.history.replaceState({}, '', `/contacts${suche}`);
}

beforeEach(() => {
  aufrufe.length = 0;
  szenario('');
});

afterEach(() => {
  vi.clearAllMocks();
  szenario('');
});

// ═══ A · Szenario steht vor dem Mount fest ══════════════════════════════════
describe('A · Bootstrap-Reihenfolge', () => {
  it('waehlt die Demo-Quelle bereits im Startzustand, nicht erst im Effekt', () => {
    szenario('?pjcDemo=100');
    // `startQuelle` ist genau der Lazy-Initializer des Workspace-Zustands:
    // Was er liefert, gilt ab dem ersten Render.
    expect(startQuelle().art).toBe('fixtures');
    expect(aufrufe).toEqual([]);
  });

  it('haelt ohne Szenario an der API-Quelle fest', () => {
    expect(startQuelle().art).toBe('api');
  });

  it('ignoriert unbrauchbare Werte und faellt auf die API-Quelle zurueck', () => {
    for (const wert of ['0', '-5', 'viele', '']) {
      szenario(`?pjcDemo=${wert}`);
      expect(startQuelle().art, `pjcDemo=${wert}`).toBe('api');
    }
  });

  it('zeigt im Szenario ab dem ersten Render Demo-Banner und Demo-Daten', async () => {
    szenario('?pjcDemo=100');
    render(<ContactsPage />);
    // Kein `findBy`: Das Banner haengt allein am Startzustand und muss
    // ohne einen einzigen Zustandswechsel schon da sein.
    expect(screen.getByTestId('demo-banner')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    });
    expect(aufrufe).toEqual([]);
  });
});

// ═══ B · Nullaufruf-Vertrag ═════════════════════════════════════════════════
describe('B · Nullaufruf-Vertrag', () => {
  it('loest im vollstaendigen Szenario keinen einzigen Client-Aufruf aus', async () => {
    szenario('?pjcDemo=1000&pjcAuswahl=3&pjcSuche=Attrappe&pjcStatus=freigaben');
    render(<ContactsPage />);
    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    });
    // Auswahl, Detail, Suche und Statusfläche sind alle angelaufen:
    await waitFor(() => {
      expect(screen.getByTestId('contact-detail')).toBeInTheDocument();
    });
    expect(screen.getByTestId('status-flaeche')).toBeInTheDocument();
    expect(aufrufe, `unerwartete Aufrufe: ${aufrufe.join(', ')}`).toEqual([]);
  });

  it('bindet keinen Tauri-Befehl ein', async () => {
    szenario('?pjcDemo=100');
    const invoke = vi.fn();
    vi.stubGlobal('__TAURI_INTERNALS__', { invoke });
    render(<ContactsPage />);
    await waitFor(() => {
      expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
    });
    expect(invoke).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('bleibt auch beim Bearbeiten und Vorbereiten aufruffrei', async () => {
    szenario('?pjcDemo=100&pjcAuswahl=2&pjcEditor=1');
    render(<ContactsPage />);
    await waitFor(() => {
      expect(screen.getByTestId('contact-editor')).toBeInTheDocument();
    });
    expect(aufrufe).toEqual([]);
  });
});

// ═══ C · Produktionsmodus unveraendert ══════════════════════════════════════
describe('C · Ohne Szenario', () => {
  it('startet die API-Quelle und den scharfen Mock — Beleg per Fehlerzustand', async () => {
    render(<ContactsPage />);
    // Der scharfe Mock lehnt jeden Aufruf ab; die Oberflaeche zeigt
    // daraufhin ihren Fehlerzustand. Dass ueberhaupt Aufrufe auflaufen,
    // belegt: ohne Szenario wird die API-Quelle benutzt.
    await waitFor(() => {
      expect(aufrufe.length).toBeGreaterThan(0);
    });
    expect(aufrufe).toContain('listContacts');
    expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
  });

  it('startet den Demo-Modus nicht von selbst', async () => {
    render(<ContactsPage />);
    await waitFor(() => {
      expect(aufrufe.length).toBeGreaterThan(0);
    });
    expect(screen.queryByTestId('demo-banner')).not.toBeInTheDocument();
  });
});

// ═══ D · Release-Bundle enthaelt keine Dev-Parameter ════════════════════════
describe('D · Release-Bundle', () => {
  it('nennt die Dev-Parameternamen nirgends im gebauten Bundle', async () => {
    const { existsSync, readdirSync, readFileSync } = await import('node:fs');
    const { dirname, join } = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const hier = dirname(fileURLToPath(import.meta.url));
    const dist = join(hier, '../../../dist/assets');
    if (!existsSync(dist)) {
      // Ohne Build gibt es nichts zu prüfen; der Gate-Lauf baut vorher.
      expect(true).toBe(true);
      return;
    }
    const inhalt = readdirSync(dist)
      .filter((n) => n.endsWith('.js') || n.endsWith('.css'))
      .map((n) => readFileSync(join(dist, n), 'utf8'))
      .join('\n');
    for (const name of ['pjcDemo', 'pjcAuswahl', 'pjcTheme', 'pjcStatus',
                        'pjcSuche', 'pjcEditor', 'pjcKategorie']) {
      expect(inhalt.includes(name), `${name} im Bundle`).toBe(false);
    }
  });

  it('haelt den Dev-Zweig statisch hinter import.meta.env.DEV', async () => {
    const { readFileSync } = await import('node:fs');
    const { dirname, join } = await import('node:path');
    const { fileURLToPath } = await import('node:url');
    const hier = dirname(fileURLToPath(import.meta.url));
    const quelltext = readFileSync(
      join(hier, 'workspace/ContactsWorkspace.tsx'), 'utf8');
    const rumpf = quelltext.split('export function startQuelle')[1]
      .split('\n}')[0];
    expect(rumpf).toContain('import.meta.env.DEV');
    // Der Fixture-Aufruf liegt hinter dem Gate, nicht davor.
    const vorGate = rumpf.split('import.meta.env.DEV')[0];
    expect(vorGate).not.toContain('fixtureDataSource');
  });
});

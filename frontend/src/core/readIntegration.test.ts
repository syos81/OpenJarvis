// Jarvis Core v0 — die Lese-Integration von Kontakten und Kalender.
//
// Geprüft werden die Aussagen, die diesen Block zur Safe Product Lane
// machen:
//
//  · Der Router bleibt rein und total; die bestehenden Kommandos ändern
//    ihr Verhalten nicht.
//  · Lesebefehle liefern einen Auftrag, keine Daten — und keinen Netzruf.
//  · Ein nicht erreichbares Backend meldet sich SICHTBAR und sieht nie
//    aus wie ein leeres Ergebnis.
//  · Mehrdeutige Kontaktsuchen werden nicht auf einen Treffer verengt.
//  · Aus dem Core ist kein Mutationspfad erreichbar — mechanisch, nicht
//    durch Zusicherung.

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  CORE_COMMANDS, CORE_VERSION_LINE, KONTAKT_TREFFER_LIMIT, routeCommand,
} from './commandRouter';
import { resolveRead, tagesFenster } from './readResolver';
import {
  LeseQuelleNichtErreichbar,
  type CoreReadPort, type KontaktErgebnis, type TerminTreffer,
} from './readPort';

/** Ein Port aus Fixtures — kein Server, keine realen Daten. */
function fixturePort(over: Partial<CoreReadPort> = {}): CoreReadPort {
  return {
    async sucheKontakte(): Promise<KontaktErgebnis> {
      return {
        treffer: [
          { id: 'k1', name: 'Anna Beispiel', organisation: 'Beispiel GmbH',
            emailAnzahl: 2, telefonAnzahl: 1 },
        ],
        weitereVorhanden: false,
      };
    },
    async ladeTermine(): Promise<readonly TerminTreffer[]> {
      return [
        { id: 'e1', titel: 'Testtermin', startUtc: '2026-08-11T08:00:00Z',
          endeUtc: '2026-08-11T09:00:00Z', ganztaegig: false,
          kalender: 'Privat' },
      ];
    },
    ...over,
  };
}

describe('Bestehendes Core-Verhalten bleibt', () => {
  it('status meldet unveraendert die Kernzeile', () => {
    const r = routeCommand('status');
    expect(r.kind).toBe('status');
    expect(r.lines[0]).toBe(CORE_VERSION_LINE);
  });

  it('status zeigt die aktive Route, wenn die App sie kennt', () => {
    expect(routeCommand('status', { route: '/calendar' }).lines)
      .toContain('Aktive Ansicht: /calendar');
  });

  it('unbekannte Eingaben nennen sich selbst und werfen nicht', () => {
    const r = routeCommand('quatsch');
    expect(r.kind).toBe('unknown');
    expect(r.lines[0]).toContain('quatsch');
  });

  it('die leere Eingabe bleibt total behandelt', () => {
    expect(routeCommand('').kind).toBe('unknown');
    expect(routeCommand('').lines.length).toBeGreaterThan(0);
  });

  it('help listet die tatsaechlich implementierten Kommandos', () => {
    const zeilen = routeCommand('help').lines;
    expect(zeilen).toHaveLength(CORE_COMMANDS.length);
    for (const c of CORE_COMMANDS) {
      expect(zeilen.some((z) => z.startsWith(`${c.name} —`))).toBe(true);
    }
    // Die neuen Lesekommandos sind in help sichtbar …
    expect(zeilen.some((z) => z.startsWith('kontakt —'))).toBe(true);
    expect(zeilen.some((z) => z.startsWith('termine —'))).toBe(true);
  });
});

describe('Router: Lesebefehle sind Auftraege, keine Daten', () => {
  it('kontakt <begriff> erzeugt einen Leseauftrag mit Limit', () => {
    const r = routeCommand('kontakt Anna');
    expect(r.kind).toBe('read');
    expect(r.read).toEqual({
      art: 'kontakte', query: 'Anna', limit: KONTAKT_TREFFER_LIMIT });
  });

  it('der Suchbegriff behaelt seine Schreibweise', () => {
    expect(routeCommand('kontakt Anna Beispiel').read)
      .toMatchObject({ query: 'Anna Beispiel' });
    // …das Kommando selbst wird weiterhin normalisiert.
    expect(routeCommand('KONTAKT Anna').kind).toBe('read');
  });

  it('kontakt ohne Begriff laedt NICHT den ganzen Bestand', () => {
    const r = routeCommand('kontakt');
    expect(r.kind).toBe('unknown');
    expect(r.read).toBeUndefined();
  });

  it('termine ohne Argument meint heute', () => {
    expect(routeCommand('termine').read).toEqual({ art: 'termine', tag: 'heute' });
  });

  it('termine akzeptiert morgen und ein Datum', () => {
    expect(routeCommand('termine morgen').read)
      .toEqual({ art: 'termine', tag: 'morgen' });
    expect(routeCommand('termine 2026-08-12').read)
      .toEqual({ art: 'termine', tag: '2026-08-12' });
  });

  it('ein unverstaendlicher Tag wird abgewiesen statt geraten', () => {
    const r = routeCommand('termine uebermorgen');
    expect(r.kind).toBe('unknown');
    expect(r.read).toBeUndefined();
  });
});

describe('Auflösung gegen Fixtures', () => {
  it('zeigt Kontakttreffer mit Zaehlern statt Werten', async () => {
    const r = await resolveRead(
      { art: 'kontakte', query: 'Anna', limit: 10 }, fixturePort());
    expect(r.lines[0]).toContain('1 Treffer');
    expect(r.lines[1]).toContain('Anna Beispiel');
    expect(r.lines[1]).toContain('2 E-Mail, 1 Tel.');
    // Keine Rohwerte: nirgends eine Mailadresse oder Telefonnummer.
    expect(r.lines.join('\n')).not.toMatch(/@|\+\d/);
  });

  it('verengt eine mehrdeutige Suche NICHT auf einen Treffer', async () => {
    const port = fixturePort({
      async sucheKontakte() {
        return {
          treffer: [
            { id: 'k1', name: 'Anna Beispiel', organisation: null,
              emailAnzahl: 1, telefonAnzahl: 0 },
            { id: 'k2', name: 'Anna Muster', organisation: null,
              emailAnzahl: 0, telefonAnzahl: 2 },
          ],
          weitereVorhanden: true,
        };
      },
    });
    const r = await resolveRead(
      { art: 'kontakte', query: 'Anna', limit: 10 }, port);
    expect(r.lines[0]).toContain('2 Treffer');
    expect(r.lines.some((z) => z.includes('Anna Beispiel'))).toBe(true);
    expect(r.lines.some((z) => z.includes('Anna Muster'))).toBe(true);
    // Und die Ehrlichkeit, dass es noch mehr gibt.
    expect(r.lines.some((z) => z.includes('weitere Treffer'))).toBe(true);
  });

  it('meldet ein leeres Suchergebnis als solches', async () => {
    const port = fixturePort({
      async sucheKontakte() { return { treffer: [], weitereVorhanden: false }; },
    });
    const r = await resolveRead(
      { art: 'kontakte', query: 'Zzz', limit: 10 }, port);
    expect(r.lines[0]).toContain('Keine Kontakte');
  });

  it('zeigt Termine sortiert mit Zeit, Titel und Kalender', async () => {
    const r = await resolveRead({ art: 'termine', tag: '2026-08-11' },
                                fixturePort());
    expect(r.lines[0]).toContain('2026-08-11');
    expect(r.lines[1]).toContain('Testtermin');
    expect(r.lines[1]).toContain('Privat');
  });

  it('meldet einen leeren Tag als leeren Tag', async () => {
    const port = fixturePort({ async ladeTermine() { return []; } });
    const r = await resolveRead({ art: 'termine', tag: '2026-08-11' }, port);
    expect(r.lines[0]).toContain('Keine Termine');
  });

  it('bildet ein Tagesfenster von Mitternacht bis Mitternacht', () => {
    const f = tagesFenster('2026-08-11', new Date('2026-08-11T12:00:00Z'));
    expect(f.datum).toBe('2026-08-11');
    expect(f.startUtc).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
    expect(f.endeUtc > f.startUtc).toBe(true);
  });
});

describe('Backend-Ausfall', () => {
  const tot: CoreReadPort = {
    async sucheKontakte() { throw new LeseQuelleNichtErreichbar('kontakte'); },
    async ladeTermine() { throw new LeseQuelleNichtErreichbar('termine'); },
  };

  it('Kontakte: sichtbar, verstaendlich, kein Wurf, keine leere Liste',
     async () => {
    const r = await resolveRead(
      { art: 'kontakte', query: 'Anna', limit: 10 }, tot);
    const text = r.lines.join(' ');
    expect(text).toContain('nicht verfügbar');
    expect(text).toContain('lokale Jarvis-Backend');
    // Entscheidend: NICHT als „nichts gefunden" getarnt.
    expect(text).not.toContain('Keine Kontakte');
  });

  it('Termine: dieselbe ehrliche Ansage', async () => {
    const r = await resolveRead({ art: 'termine', tag: 'heute' }, tot);
    const text = r.lines.join(' ');
    expect(text).toContain('nicht verfügbar');
    expect(text).not.toContain('Keine Termine');
  });

  it('rein lokale Kommandos bleiben davon unberuehrt', () => {
    expect(routeCommand('status').kind).toBe('status');
    expect(routeCommand('help').kind).toBe('help');
  });
});

describe('Safety: aus dem Core ist kein Mutationspfad erreichbar', () => {
  const lies = (datei: string) =>
    readFileSync(fileURLToPath(new URL(datei, import.meta.url)), 'utf8');

  const CORE_DATEIEN = [
    'commandRouter.ts', 'readPort.ts', 'readAdapter.ts', 'readResolver.ts',
    'JarvisCommandBar.tsx', 'JarvisCommandBarHost.tsx',
  ];

  /** Namen, die im Core einen produktiven Schreibweg bedeuten würden. */
  const MUTATIONSSYMBOLE = [
    'prepareCreate', 'prepareUpdate', 'prepareDelete', 'approve', 'reject',
    'execute', 'reconcile', 'assignRole', 'removeRole', 'runSync',
    'synchronisiere', 'bereiteVor', 'bereiteUpdateVor', 'bereiteLoeschenVor',
    'gibFrei', 'beanspruche', 'fuehreAus', 'schliesseAb',
    'personal_calendar_execute_mutation', 'personal_calendar_delete_probe',
  ];

  it('keine Core-Datei nennt ein Mutationssymbol', () => {
    // R10: erst belegen, dass der Scan auf Material laeuft.
    const inhalte = CORE_DATEIEN.map((d) => [d, lies(d)] as const);
    expect(inhalte.every(([, text]) => text.length > 200)).toBe(true);

    const treffer: string[] = [];
    for (const [datei, text] of inhalte) {
      // Kommentare ausblenden: geprueft wird Code, nicht Prosa.
      const code = text.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
      for (const symbol of MUTATIONSSYMBOLE) {
        if (code.includes(symbol)) treffer.push(`${datei}:${symbol}`);
      }
    }
    expect(treffer).toEqual([]);
  });

  it('nur der Adapter importiert die Fachmodule — und nur deren Leser', () => {
    for (const datei of CORE_DATEIEN) {
      const code = lies(datei).replace(/\/\/[^\n]*/g, '');
      const importiertFachmodul = /from '\.\.\/personal\//.test(code);
      if (datei !== 'readAdapter.ts') {
        expect(importiertFachmodul, `${datei} importiert ein Fachmodul`)
          .toBe(false);
      }
    }
    const adapter = lies('readAdapter.ts').replace(/\/\/[^\n]*/g, '');
    // Genau zwei Leseimporte, nichts sonst aus den Fachmodulen.
    expect(adapter).toContain("import { listContacts }");
    expect(adapter).toContain('ladeTermine as ladeTermineApi');
    expect(adapter).not.toContain('DataSource');
  });

  it('der Lese-Port traegt typseitig keine Mutationsoperation', () => {
    // Kommentare ausblenden: der Port BENENNT in seiner Doku bewusst, was
    // er nicht kann — geprueft wird der Code.
    const port = lies('readPort.ts')
      .replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
    expect(port).toContain('sucheKontakte');
    expect(port).toContain('ladeTermine');
    for (const symbol of MUTATIONSSYMBOLE) {
      expect(port.includes(symbol), `readPort nennt ${symbol}`).toBe(false);
    }
  });

  it('CORE_COMMANDS bietet kein schreibendes Kommando an', () => {
    const verboten = ['create', 'anlegen', 'update', 'aendern', 'delete',
                      'loeschen', 'löschen', 'sync'];
    for (const c of CORE_COMMANDS) {
      for (const wort of verboten) {
        expect(c.name.includes(wort), `Kommando ${c.name}`).toBe(false);
      }
    }
  });
});

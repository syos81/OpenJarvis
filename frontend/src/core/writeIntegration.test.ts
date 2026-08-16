// Jarvis Core v0 — die Schreib-Integration (Risk Lane).
//
// Geprüft werden genau die Bedingungen, unter denen dieser Block eine
// echte Mutation überhaupt erreichbar machen darf:
//
//  · Vorbereiten mutiert nie; ausgeführt wird ausschliesslich über eine
//    ausdrückliche, an DIESE eine Operation gebundene Freigabe.
//  · Eine Freigabe für A führt B nicht aus; dieselbe Freigabe wirkt kein
//    zweites Mal.
//  · Mehrdeutige Ziele werden nie automatisch aufgelöst.
//  · Ein veränderter Vorzustand, ein toter Backend, eine fehlende
//    Berechtigung: jedes Mal fail-closed, ohne Mutation.
//  · Calendar DELETE ist aus dem Core nicht erreichbar — mechanisch.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CORE_COMMANDS, routeCommand } from './commandRouter';
import { neuerSchacht, resolveWrite, type FreigabeSchacht } from './writeResolver';
import {
  SchreibFehler,
  type AusgefuehrteMutation, type CoreWritePort, type VorbereiteteMutation,
} from './writePort';

/** Ein Port, der zählt statt zu mutieren. Der Zähler IST der Beleg. */
function zaehlPort(over: Partial<CoreWritePort> = {}) {
  const zaehler = { vorbereitet: 0, freigegeben: 0, ausgefuehrt: 0 };
  const vorbereitung = (operation: VorbereiteteMutation['operation'],
                        mutationId: string): VorbereiteteMutation => ({
    operation, mutationId, kanal: 'kontakte',
    vorschau: [`Operation: ${operation}`], gebundenerZustand: 'rev-1',
    ziel: { id: 'k1', bezeichnung: 'Test Person', container: null },
  });
  const port: CoreWritePort = {
    async findeKontakt(query) {
      if (query === 'mehrdeutig') throw new SchreibFehler('ziel_mehrdeutig', '3');
      if (query === 'unbekannt') throw new SchreibFehler('ziel_nicht_gefunden');
      if (query === 'totesbackend') {
        throw new SchreibFehler('quelle_nicht_erreichbar');
      }
      return { id: 'k1', bezeichnung: 'Test Person', container: null };
    },
    async findeTermin() {
      return { id: 'e1', bezeichnung: 'Testtermin', container: 'cal-1' };
    },
    async bereiteKontaktAnlegenVor() {
      zaehler.vorbereitet += 1; return vorbereitung('kontakt_anlegen', 'm-neu');
    },
    async bereiteKontaktAendernVor() {
      zaehler.vorbereitet += 1; return vorbereitung('kontakt_aendern', 'm-upd');
    },
    async bereiteKontaktLoeschenVor() {
      zaehler.vorbereitet += 1; return vorbereitung('kontakt_loeschen', 'm-del');
    },
    async bereiteTerminAnlegenVor() {
      zaehler.vorbereitet += 1; return vorbereitung('termin_anlegen', 'm-tneu');
    },
    async bereiteTerminAendernVor() {
      zaehler.vorbereitet += 1; return vorbereitung('termin_aendern', 'm-tupd');
    },
    async genehmige() {
      zaehler.freigegeben += 1;
    },
    async fuehreAus(v): Promise<AusgefuehrteMutation> {
      zaehler.ausgefuehrt += 1;
      return {
        operation: v.operation, mutationId: v.mutationId,
        readback: ['Gelesen: Test Person'], readbackBestaetigt: true,
      };
    },
    ...over,
  };
  return { port, zaehler };
}

let schacht: FreigabeSchacht;
beforeEach(() => { schacht = neuerSchacht(); });

describe('Router: Schreibbefehle bereiten vor, sie fuehren nicht aus', () => {
  it('kontakt-neu erzeugt eine prepare-Phase', () => {
    const r = routeCommand('kontakt-neu C-1b3d99 | Max Mustermann');
    expect(r.kind).toBe('write_prepare');
    expect(r.write).toEqual({
      phase: 'prepare', operation: 'kontakt_anlegen',
      ziel: 'C-1b3d99', name: 'Max Mustermann' });
  });

  it('kontakt-aendern zerlegt Ziel, Feld und Wert', () => {
    const r = routeCommand('kontakt-aendern Max | position = Chef');
    expect(r.write).toEqual({
      phase: 'prepare', operation: 'kontakt_aendern',
      query: 'Max', feld: 'position', wert: 'Chef' });
  });

  it('kontakt-loeschen erzeugt nur eine Vorbereitung', () => {
    const r = routeCommand('kontakt-loeschen Max');
    expect(r.kind).toBe('write_prepare');
    expect(r.write).toMatchObject({ phase: 'prepare',
                                    operation: 'kontakt_loeschen' });
  });

  it('termin-neu und termin-aendern ebenso', () => {
    expect(routeCommand('termin-neu Jarvis Livetest | heute | 09:00-10:00 | Test').write)
      .toEqual({ phase: 'prepare', operation: 'termin_anlegen',
                 ziel: 'Jarvis Livetest', tag: 'heute',
                 vonBis: '09:00-10:00', titel: 'Test' });
    expect(routeCommand('termin-aendern heute | Test | Neu').write)
      .toEqual({ phase: 'prepare', operation: 'termin_aendern',
                 tag: 'heute', query: 'Test', neuerTitel: 'Neu' });
  });

  it('unvollstaendige Eingaben erzeugen KEINEN Schreibauftrag', () => {
    for (const eingabe of [
      'kontakt-neu', 'kontakt-neu C-1b3d99', 'kontakt-aendern Max',
      'kontakt-aendern Max | position =', 'kontakt-loeschen',
      'termin-neu heute | 09:00-10:00 | Test',
      'termin-neu Privat | heute | kaputt | Test',
      'termin-aendern heute | Test', 'freigabe',
    ]) {
      const r = routeCommand(eingabe);
      expect(r.kind, eingabe).toBe('unknown');
      expect(r.write, eingabe).toBeUndefined();
    }
  });

  it('nur `ausfuehren` kann eine Ausfuehrung anfordern', () => {
    // Seit 2026-08-16 ist `freigabe` KEIN Ausfuehrungsbefehl mehr: es gibt
    // frei und laesst den Vorgang offen. Vorher loeste dasselbe Kommando
    // beides aus, und im Kalenderzweig holte der Ausfuehrungsschritt die
    // Freigabe zusaetzlich selbst nach.
    const ausfuehrend = ['status', 'help', 'kontakt Max', 'termine heute',
                         'kontakt-neu C-1 | Max', 'kontakt-loeschen Max',
                         'freigabe m-1']
      .map((e) => routeCommand(e))
      .filter((r) => r.write?.phase === 'execute');
    expect(ausfuehrend).toEqual([]);
    expect(routeCommand('freigabe m-1').write)
      .toEqual({ phase: 'approve', mutationId: 'm-1' });
    expect(routeCommand('ausfuehren m-1').write)
      .toEqual({ phase: 'execute', mutationId: 'm-1' });
  });

  it('`ausfuehren` ohne Kennung fuehrt nichts aus', () => {
    const r = routeCommand('ausfuehren');
    expect(r.kind).toBe('unknown');
    expect(r.write).toBeUndefined();
  });
});

describe('Freigabemechanik', () => {
  it('Vorschau mutiert nicht und nennt die Kennung', async () => {
    const { port, zaehler } = zaehlPort();
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    expect(r.kind).toBe('write_prepare');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('Noch ist nichts geändert');
    expect(r.lines.some((z) => z.includes('freigabe m-neu'))).toBe(true);
  });

  it('ohne Vorbereitung fuehrt eine Freigabe nichts aus', async () => {
    const { port, zaehler } = zaehlPort();
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('keine vorbereitete Mutation');
  });

  it('eine Freigabe fuer eine ANDERE Operation fuehrt nichts aus', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'Max' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('anderen Operation');
  });

  it('die passende Freigabe fuehrt genau einmal aus', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(1);
    expect(r.lines[0]).toContain('durch frischen Readback bestätigt');
  });

  it('dieselbe Freigabe wirkt kein zweites Mal', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    await resolveWrite({ phase: 'execute', mutationId: 'm-neu' }, port, schacht, 'lukas');
    const zweite = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                      port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(1);
    expect(zweite.lines.join(' ')).toContain('keine vorbereitete Mutation');
  });

  it('abbrechen verwirft ohne Ausfuehrung', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'Max' },
      port, schacht, 'lukas');
    await resolveWrite({ phase: 'abort' }, port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-del' },
                                 port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('keine vorbereitete Mutation');
  });

  it('eine zweite Vorbereitung ersetzt die erste — kein Stapel', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'Max' },
      port, schacht, 'lukas');
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    // Die ALTE Kennung ist damit wertlos.
    const alt = await resolveWrite({ phase: 'execute', mutationId: 'm-del' },
                                   port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(alt.lines.join(' ')).toContain('anderen Operation');
  });
});

describe('Fail-closed in jedem geforderten Fehlerfall', () => {
  it('Mehrdeutigkeit waehlt NICHT aus', async () => {
    const { port, zaehler } = zaehlPort();
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'mehrdeutig' },
      port, schacht, 'lukas');
    expect(zaehler.vorbereitet).toBe(0);
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('Mehrere Treffer');
    expect(schacht.offen).toBeNull();
  });

  it('Ziel nicht gefunden: keine Vorbereitung', async () => {
    const { port, zaehler } = zaehlPort();
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_aendern', query: 'unbekannt',
        feld: 'position', wert: 'X' }, port, schacht, 'lukas');
    expect(zaehler.vorbereitet).toBe(0);
    expect(r.lines.join(' ')).toContain('Kein passendes Ziel');
  });

  it('Backend tot: keine Vorbereitung, keine Mutation', async () => {
    const { port, zaehler } = zaehlPort();
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'totesbackend' },
      port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('nicht erreichbar');
  });

  it('Ziel zwischen Vorschau und Execute veraendert: kein Write', async () => {
    const { port, zaehler } = zaehlPort({
      async fuehreAus() { throw new SchreibFehler('ziel_veraendert'); },
    });
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_aendern', query: 'Max',
        feld: 'position', wert: 'Chef' }, port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-upd' },
                                 port, schacht, 'lukas');
    expect(zaehler.ausgefuehrt).toBe(0);
    expect(r.lines.join(' ')).toContain('seit der Vorschau geändert');
    expect(r.lines.join(' ')).toContain('neu freigeben');
  });

  it('fehlende Berechtigung: benannt, ohne Mutation', async () => {
    const { port } = zaehlPort({
      async fuehreAus() { throw new SchreibFehler('keine_berechtigung'); },
    });
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(r.lines.join(' ')).toContain('Berechtigung fehlt');
  });

  it('Zielcontainer weg: keine Vorbereitung', async () => {
    const { port } = zaehlPort({
      async bereiteKontaktAnlegenVor() {
        throw new SchreibFehler('container_nicht_verfuegbar');
      },
    });
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    expect(r.lines.join(' ')).toContain('Kein eindeutiger Zielort');
    expect(schacht.offen).toBeNull();
  });

  it('widersprechender Readback wird NICHT als Erfolg gemeldet', async () => {
    const { port } = zaehlPort({
      async fuehreAus(v) {
        return { operation: v.operation, mutationId: v.mutationId,
                 readbackBestaetigt: false,
                 readback: ['Der Kontakt ist weiterhin abrufbar.'] };
      },
    });
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'Max' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-del' },
                                 port, schacht, 'lukas');
    expect(r.lines[0]).toContain('bestätigt es NICHT');
  });

  it('Ausfuehrung fehlgeschlagen: benannt', async () => {
    const { port } = zaehlPort({
      async fuehreAus() {
        throw new SchreibFehler('ausfuehrung_fehlgeschlagen', 'provider_error');
      },
    });
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'Max' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(r.lines.join(' ')).toContain('fehlgeschlagen');
    expect(r.lines.join(' ')).toContain('provider_error');
  });
});

describe('Kein stilles Schreiben', () => {
  it('Lesebefehle und status/help erzeugen nie einen Schreibauftrag', () => {
    for (const eingabe of ['status', 'help', '', 'kontakt Max', 'termine heute',
                           'termine', 'quatsch']) {
      expect(routeCommand(eingabe).write, eingabe).toBeUndefined();
    }
  });

  it('ein Lesebefehl laesst eine offene Vorbereitung unangetastet', async () => {
    const { port, zaehler } = zaehlPort();
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_loeschen', query: 'Max' },
      port, schacht, 'lukas');
    // Ein Read dazwischen fuehrt nichts aus …
    expect(routeCommand('kontakt Max').write).toBeUndefined();
    expect(zaehler.ausgefuehrt).toBe(0);
    // … und verbraucht die Freigabe auch nicht.
    expect(schacht.offen?.mutationId).toBe('m-del');
  });
});

describe('Calendar DELETE ist aus dem Core nicht erreichbar', () => {
  const lies = (datei: string) =>
    readFileSync(fileURLToPath(new URL(datei, import.meta.url)), 'utf8');
  const OHNE_KOMMENTARE = (t: string) =>
    t.replace(/\/\/[^\n]*/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  const CORE_DATEIEN = [
    'commandRouter.ts', 'readPort.ts', 'readAdapter.ts', 'readResolver.ts',
    'writePort.ts', 'writeAdapter.ts', 'writeResolver.ts',
    'JarvisCommandBar.tsx', 'JarvisCommandBarHost.tsx',
  ];

  it('keine Core-Datei nennt einen Kalender-Loeschpfad', () => {
    const inhalte = CORE_DATEIEN.map((d) => [d, OHNE_KOMMENTARE(lies(d))] as const);
    // R10: erst belegen, dass der Scan auf Material laeuft.
    expect(inhalte.every(([, t]) => t.length > 150)).toBe(true);
    const verboten = ['bereiteLoeschenVor', 'erhebeLoeschProbe',
                      'TerminLoeschen', 'personal_calendar_delete_probe',
                      'termin_loeschen', 'termin-loeschen'];
    const treffer: string[] = [];
    for (const [datei, code] of inhalte) {
      for (const s of verboten) if (code.includes(s)) treffer.push(`${datei}:${s}`);
    }
    expect(treffer).toEqual([]);
  });

  it('der Schreib-Port kennt typseitig kein Termin-Loeschen', () => {
    const port = OHNE_KOMMENTARE(lies('writePort.ts'));
    expect(port).toContain('termin_anlegen');
    expect(port).toContain('termin_aendern');
    expect(port).not.toContain('termin_loeschen');
    // Genau fuenf Operationen, nicht sechs.
    const operationen = port.match(/'(kontakt|termin)_[a-z]+'/g) ?? [];
    expect(new Set(operationen).size).toBe(5);
  });

  it('CORE_COMMANDS bietet kein Kalender-Loeschkommando an', () => {
    const namen = CORE_COMMANDS.map((c) => c.name);
    expect(namen).toContain('termin-neu');
    expect(namen).toContain('termin-aendern');
    expect(namen.some((n) => n.startsWith('termin') && n.includes('loesch')))
      .toBe(false);
  });

  it('eine erfundene Loescheingabe wird als unbekannt behandelt', () => {
    for (const eingabe of ['termin-loeschen heute | Test',
                           'termin loeschen', 'kalender-loeschen Test']) {
      const r = routeCommand(eingabe);
      expect(r.kind, eingabe).toBe('unknown');
      expect(r.write, eingabe).toBeUndefined();
    }
  });

  it('der Adapter importiert keinen Kalender-Loeschweg', () => {
    const adapter = OHNE_KOMMENTARE(lies('writeAdapter.ts'));
    expect(adapter).toContain('bereiteUpdateVor');
    expect(adapter).toContain('bereiteVor');
    expect(adapter).not.toContain('bereiteLoeschenVor');
    expect(adapter).not.toContain('erhebeLoeschProbe');
  });
});

describe('help bleibt wahrheitsgemaess', () => {
  it('listet jedes implementierte Kommando und nichts darueber hinaus', () => {
    const zeilen = routeCommand('help').lines;
    expect(zeilen).toHaveLength(CORE_COMMANDS.length);
    for (const c of CORE_COMMANDS) {
      expect(zeilen.some((z) => z.startsWith(`${c.name} —`)), c.name).toBe(true);
    }
  });

  it('die bestehenden Lese- und Statusbefehle sind unveraendert da', () => {
    const namen = CORE_COMMANDS.map((c) => c.name);
    for (const n of ['status', 'help', 'kontakt', 'termine']) {
      expect(namen).toContain(n);
    }
    expect(routeCommand('status').kind).toBe('status');
    expect(routeCommand('kontakt Max').kind).toBe('read');
    expect(routeCommand('termine').kind).toBe('read');
  });
});

// ── Livebefund 2026-08-11: der Fehlertext war selbst ein Mangel ───────────
//
// Erste reale Eingabe `kontakt-neu C-4b8df1 | Jarvis Schreibtest` meldete
// nur „Die Ausfuehrung ist fehlgeschlagen". Zwei Defekte in einem Satz:
// es wurde nichts AUSGEFUEHRT (der Vorbereitungsschritt scheiterte), und
// der typisierte Grund des Servers (`unsupported`, „Operation 'create'
// ist nicht deklariert") wurde weggeworfen. Beides ist hier gepinnt.

describe('Diagnosepflicht der Fehlermeldung', () => {
  it('ein Scheitern beim Vorbereiten heisst NICHT Ausfuehrung', async () => {
    const { port } = zaehlPort({
      async bereiteKontaktAnlegenVor() {
        throw new SchreibFehler('operation_nicht_freigeschaltet',
                                "Operation 'create' ist nicht deklariert",
                                'vorbereiten', 'unsupported');
      },
    });
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-4b8df1',
        name: 'Jarvis Schreibtest' }, port, schacht, 'lukas');
    const text = r.lines.join(' | ');
    expect(text).toContain('Vorbereitung ist fehlgeschlagen');
    expect(text).not.toContain('Ausführung ist fehlgeschlagen');
  });

  it('der typisierte Servergrund erreicht den Menschen', async () => {
    const { port } = zaehlPort({
      async bereiteKontaktAnlegenVor() {
        throw new SchreibFehler('operation_nicht_freigeschaltet',
                                "Operation 'create' ist nicht deklariert",
                                'vorbereiten', 'unsupported');
      },
    });
    const r = await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-4b8df1',
        name: 'Jarvis Schreibtest' }, port, schacht, 'lukas');
    const text = r.lines.join(' | ');
    expect(text).toContain('operation_nicht_freigeschaltet');
    expect(text).toContain("Operation 'create' ist nicht deklariert");
    expect(text).toContain('unsupported');
    expect(text).toContain('nicht freigeschaltet');
  });

  it('jede Fehlermeldung sagt, dass nichts geaendert wurde', async () => {
    const faelle: SchreibFehler[] = [
      new SchreibFehler('operation_nicht_freigeschaltet', 'x', 'vorbereiten'),
      new SchreibFehler('quelle_nicht_erreichbar', undefined, 'vorbereiten'),
      new SchreibFehler('ziel_mehrdeutig', '3', 'vorbereiten'),
    ];
    for (const f of faelle) {
      const { port } = zaehlPort({
        async bereiteKontaktAnlegenVor() { throw f; },
      });
      const r = await resolveWrite(
        { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1',
          name: 'X' }, port, schacht, 'lukas');
      expect(r.lines.join(' '), f.art).toContain('nichts');
      expect(schacht.offen, f.art).toBeNull();
    }
  });

  it('ein Fehler beim Ausfuehren behaelt seine eigene Wortwahl', async () => {
    const { port } = zaehlPort({
      async fuehreAus() {
        throw new SchreibFehler('ausfuehrung_fehlgeschlagen', 'provider_error',
                                'ausfuehren', 'internal');
      },
    });
    await resolveWrite(
      { phase: 'prepare', operation: 'kontakt_anlegen', ziel: 'C-1', name: 'X' },
      port, schacht, 'lukas');
    const r = await resolveWrite({ phase: 'execute', mutationId: 'm-neu' },
                                 port, schacht, 'lukas');
    expect(r.lines.join(' ')).toContain('Ausführung ist fehlgeschlagen');
  });
});

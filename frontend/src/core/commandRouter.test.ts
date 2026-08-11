// Der lokale Router — geprüft wird, was er zusagt und was er unterlässt.
//
// Läuft ohne DOM in der Repo-Standardumgebung `node`: der Router ist rein,
// also braucht sein Test weder Browser noch Netzwerkattrappe.

import { describe, expect, it } from 'vitest';
import { CORE_COMMANDS, CORE_VERSION_LINE, routeCommand } from './commandRouter';

describe('status', () => {
  it('meldet den Core als aktiv', () => {
    const r = routeCommand('status');
    expect(r.kind).toBe('status');
    expect(r.lines[0]).toBe(CORE_VERSION_LINE);
  });

  it('zeigt den bekannten UI-Kontext, wenn es einen gibt', () => {
    const r = routeCommand('status', { route: '/calendar' });
    expect(r.lines).toContain('Aktive Ansicht: /calendar');
  });

  it('erfindet keinen Kontext, wenn keiner vorliegt', () => {
    const r = routeCommand('status');
    expect(r.lines).toEqual([CORE_VERSION_LINE]);
  });

  it('nimmt Leerraum und Grossschreibung hin', () => {
    expect(routeCommand('  STATUS  ').kind).toBe('status');
  });
});

describe('help', () => {
  it('listet jedes implementierte Kommando', () => {
    const r = routeCommand('help');
    expect(r.kind).toBe('help');
    for (const c of CORE_COMMANDS) {
      expect(r.lines.some((z) => z.startsWith(`${c.name} —`))).toBe(true);
    }
  });

  it('behauptet nichts über das Implementierte hinaus', () => {
    // Eine Zeile je Kommando, keine Zeile mehr: so kann `help` keine
    // Fähigkeit vortäuschen, die der Router nicht kennt.
    expect(routeCommand('help').lines).toHaveLength(CORE_COMMANDS.length);
  });
});

describe('unbekannter Befehl', () => {
  it('antwortet sichtbar statt zu scheitern', () => {
    const r = routeCommand('kalender aufräumen');
    expect(r.kind).toBe('unknown');
    expect(r.lines[0]).toContain('kalender aufräumen');
    expect(r.lines[1]).toContain('status');
    expect(r.lines[1]).toContain('help');
  });

  it('behandelt die leere Eingabe als eigenen sichtbaren Fall', () => {
    const r = routeCommand('   ');
    expect(r.kind).toBe('unknown');
    expect(r.command).toBe('');
    expect(r.lines[0]).toBe('Kein Befehl eingegeben.');
  });

  it('wirft nie — jede Eingabe bekommt ein Ergebnis', () => {
    for (const eingabe of ['', '?', 'status status', 'DROP TABLE', '🙂']) {
      expect(() => routeCommand(eingabe)).not.toThrow();
      expect(routeCommand(eingabe).lines.length).toBeGreaterThan(0);
    }
  });
});

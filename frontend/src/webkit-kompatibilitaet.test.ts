/**
 * Was die Zielplattform tatsächlich versteht.
 *
 * Der Kalender hat diese Grenze in B2 gefunden und für seine Tokens
 * abgesichert; am 2026-08-16 fiel auf, dass sie für den Rest der Oberfläche
 * nie galt: 47 Stellen bauten Farben mit `color-mix()`, und auf dem Intel-Mac
 * (WebKit 17613, Safari-15.6-Ära) fielen sie **stumm** aus — der farbige
 * Avatarkreis, Hover, Trennlinien, Statusflächen.
 *
 * Gemessen mit einer WKWebView-Probe gegen die System-Engine:
 *
 *   CSS.supports('background-color','color-mix(in srgb, #0a84ff 12%, transparent)')
 *     → false
 *   getComputedStyle(…).backgroundColor  →  rgba(0, 0, 0, 0)
 *
 * Ein stumm ausfallender Wert ist die unangenehmste Sorte Fehler: Es sieht
 * nach Absicht aus. Dieser Test hält die Grenze fest, damit sie nicht ein
 * drittes Mal einzeln entdeckt werden muss.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const WURZEL = dirname(fileURLToPath(import.meta.url));

function quellen(verzeichnis: string): string[] {
  return readdirSync(verzeichnis).flatMap((name) => {
    const pfad = join(verzeichnis, name);
    if (statSync(pfad).isDirectory()) {
      return name === 'node_modules' ? [] : quellen(pfad);
    }
    return ['.ts', '.tsx', '.css'].includes(extname(name)) ? [pfad] : [];
  });
}

/** Kommentare dürfen die Grenze beim Namen nennen — sie erklären sie. */
function ohneKommentare(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((z) => !z.trimStart().startsWith('//') && !z.trimStart().startsWith('*'))
    .join('\n');
}

describe('CSS-Merkmale, die die Zielplattform nicht kennt', () => {
  it('verwendet nirgends color-mix()', () => {
    const treffer = quellen(WURZEL)
      .filter((p) => !p.includes('.test.'))
      .filter((p) => ohneKommentare(readFileSync(p, 'utf8')).includes('color-mix('))
      .map((p) => p.slice(WURZEL.length + 1));
    expect(treffer, 'color-mix() faellt auf WebKit 15 stumm aus — '
      + 'stattdessen rgba(var(--<token>-rgb), <alpha>) verwenden').toEqual([]);
  });

  it('bietet zu jedem gemischten Token die RGB-Komponenten an', () => {
    const css = readFileSync(join(WURZEL, 'index.css'), 'utf8');
    for (const name of ['text', 'text-secondary', 'surface', 'accent',
                        'accent-purple', 'success', 'warning', 'error']) {
      expect(css, `--color-${name}-rgb fehlt`).toContain(`--color-${name}-rgb:`);
    }
    // In allen drei Theme-Bereichen: hell, .dark und prefers-color-scheme.
    expect(css.match(/--color-error-rgb:/g)?.length).toBe(3);
  });

  it('der Scan ist nicht leer', () => {
    // Ein Waechter, der nichts liest, meldet immer gruen.
    expect(quellen(WURZEL).length).toBeGreaterThan(100);
  });
});

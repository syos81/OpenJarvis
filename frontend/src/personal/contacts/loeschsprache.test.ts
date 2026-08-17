// Die Sprache des Löschens — verbindlich, nicht nach Geschmack.
//
// Jarvis darf sagen: „Kontaktinhalt wiederherstellbar."
// Jarvis darf **nicht** sagen: „Kontakt wiederherstellbar" oder „restorable".
//
// Der Unterschied ist kein Wortklauben. Wer „der Kontakt kommt wieder" liest,
// plant anders als jemand, der weiss, dass die Providerkennung weg ist und
// externe Verknüpfungen daran hängen. Kurzform der Regel:
// content-recoverable, identity-irreversible.

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const WURZEL = join(__dirname);

/**
 * Der Quelltext **ohne Kommentare** und mit zusammengezogenem Weissraum.
 *
 * Beides ist nötig, und beides aus einem Grund: Geprüft wird, was Jarvis
 * *sagt*, nicht was der Code *erklärt*. Ein Kommentar, der die alte
 * Formulierung zitiert, um zu begründen, warum sie weg ist, darf diese
 * Prüfung nicht auslösen — sonst könnte man die Entscheidung nicht mehr
 * dokumentieren, ohne den Test zu brechen.
 *
 * Der Weissraum wird zusammengezogen, damit „mit neuer\n Providerkennung"
 * derselbe Satz ist wie „mit neuer Providerkennung": Ein Test, der beim
 * Umbrechen rot wird, prüft die Formatierung statt die Aussage.
 */
function quelle(name: string): string {
  return readFileSync(join(WURZEL, name), 'utf-8')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
    .replace(/\s+/g, ' ');
}

/** Die Dateien, die über eine Löschung sprechen. */
const LOESCHFLAECHEN = [
  'editor/dialogs.tsx',
  'status/ContactsStatusSurface.tsx',
  'settings/SchreibfreigabeSchalter.tsx',
];

describe('Die Sprache des Löschens', () => {
  it('sagt „Kontaktinhalt", nicht „Kontakt" wiederherstellbar', () => {
    for (const name of LOESCHFLAECHEN) {
      const text = quelle(name);
      // Jedes „wiederherstellbar" muss sich auf den Inhalt beziehen.
      for (const treffer of text.matchAll(/(\S+)\s+(?:bleibt\s+)?wiederherstellbar/gi)) {
        expect(treffer[1].toLowerCase(), `${name}: „${treffer[0]}"`)
          .toMatch(/kontaktinhalt/);
      }
    }
  });

  it('verwendet nirgends „restorable"', () => {
    for (const name of LOESCHFLAECHEN) {
      expect(quelle(name).toLowerCase(), name).not.toContain('restorable');
    }
  });

  it('behauptet nicht mehr, ein Löschen sei nicht rückgängig zu machen', () => {
    // Bis zum Löschgate stand das an zwei Stellen. Es ist seitdem der
    // ungenauere Satz: Der Inhalt ist sehr wohl wiederherstellbar.
    for (const name of LOESCHFLAECHEN) {
      expect(quelle(name).toLowerCase(), name)
        .not.toContain('nicht rückgängig');
    }
  });

  it('nennt in der Löschvorschau die neue Providerkennung und die Folgen', () => {
    const text = quelle('editor/dialogs.tsx');
    expect(text).toContain('neuer Providerkennung');
    expect(text).toContain('externe Verknüpfungen');
    expect(text).toContain('verloren bleiben');
  });

  it('nennt den Ablageort der Sicherungen und dass sie liegen bleiben', () => {
    const text = quelle('settings/SchreibfreigabeSchalter.tsx');
    expect(text).toContain('~/.openjarvis/personal/backups/contacts/field-state/');
    expect(text).toContain('bleiben liegen');
  });

  it('bietet keinen Aufräumknopf für die Sicherungen', () => {
    // Löschen ist Eigentümersache. Ein Knopf dafür wäre ein Knopf, der
    // Belege beseitigt.
    const text = quelle('settings/SchreibfreigabeSchalter.tsx').toLowerCase();
    for (const wort of ['aufräumen', 'löschen</button', 'sicherungen entfernen']) {
      expect(text, wort).not.toContain(wort);
    }
  });
});

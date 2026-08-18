/**
 * @vitest-environment jsdom
 *
 * Die Materialfläche und die Lesbarkeitsregel.
 *
 * Zwei Aussagen, und die zweite ist die verbindliche:
 *
 * 1. Alle grossflächigen Hintergründe laufen über **eine** Definition, damit
 *    der Fensterumbau an einer Stelle durchträgt statt an dreissig.
 * 2. Die produktive Vorschau bleibt undurchsichtig — auch mit Systemmaterial
 *    hinter dem Fenster. Das ist gesetzt und keine Abwägung.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { Modal, Zielangabe } from './components';

const HIER = dirname(fileURLToPath(import.meta.url));
const INDEX_CSS = readFileSync(join(HIER, '../../index.css'), 'utf-8');
const TOKENS_CSS = readFileSync(join(HIER, 'tokens.css'), 'utf-8');

describe('Die Oberflächendefinition', () => {
  it('kennt eine Grundfläche, eine aufliegende und eine undurchsichtige', () => {
    for (const name of ['--surface-material', '--surface-material-raised',
                        '--surface-opaque']) {
      expect(INDEX_CSS).toContain(`${name}:`);
    }
  });

  it('schaltet die Grundfläche nur unter dem Materialattribut um', () => {
    // Ohne das Attribut greift der Block nie — im Browser, im Test und nach
    // einer Rücknahme des Fensterumbaus bleibt die Annäherung stehen.
    expect(INDEX_CSS).toContain(':root[data-material="native"]');
    // Ohne Kommentare geprüft: Der Block *begründet* dort, warum die
    // undurchsichtige Fläche fehlt. Eine Prüfung, die daran scheitert,
    // bestrafte die Begründung statt den Code.
    const block = INDEX_CSS.split(':root[data-material="native"]')[1]
      .split('}')[0].replace(/\/\*[\s\S]*?\*\//g, '');
    expect(block).toContain('--surface-material: transparent');
    expect(block).not.toContain('--surface-opaque');
  });

  it('führt die drei Kontaktflächen über die Definition, nicht an ihr vorbei', () => {
    for (const zeile of ['--pjc-bg-sidebar: var(--surface-material-raised)',
                         '--pjc-bg-list: var(--surface-material)',
                         '--pjc-bg-detail: var(--surface-material)']) {
      expect(TOKENS_CSS).toContain(zeile);
    }
  });

  it('malt den Fensterboden über die Definition', () => {
    // Der Ausgangspunkt der Messung: `body { background-color }`.
    expect(INDEX_CSS).toContain('background-color: var(--surface-material)');
  });
});

describe('Die Lesbarkeitsregel an der produktiven Vorschau', () => {
  const vorschau = (
    <Modal open onClose={() => {}} title="Änderung freigeben">
      <Zielangabe
        command="delete"
        targetLabel="Fixture Eins"
        containerRef="ct-9f3a"
        containerType="carddav"
        containerName="Arbeit"
        containerContactCount={42}
      />
    </Modal>
  );

  it('gibt der Vorschaufläche die undurchsichtige Definition', () => {
    render(vorschau);
    const flaeche = screen.getByRole('dialog');
    expect(flaeche.getAttribute('data-surface')).toBe('opaque');
    // Nicht `--surface-material`: Die Fläche darf das Material nicht
    // durchlassen, sonst steht die Vorschau darauf statt darüber.
    expect(flaeche.style.backgroundColor).toContain('--surface-opaque');
    expect(flaeche.style.backgroundColor).not.toContain('--surface-material');
  });

  it('zeigt weiterhin Ablageort, Art, Anzahl, Ziel und Operation', () => {
    render(vorschau);
    // Das Abnahmekriterium, wörtlich nachgemessen — nicht die Fläche, sondern
    // was auf ihr lesbar ist.
    expect(screen.getByTestId('zielangabe')).toBeTruthy();
    const ablageort = screen.getByTestId('zielangabe-ablageort');
    expect(ablageort.textContent).toContain('Arbeit');
    expect(ablageort.textContent).toContain('42');
    expect(screen.getByTestId('zielangabe-art').textContent?.trim()).toBeTruthy();
    expect(screen.getByText('Fixture Eins')).toBeTruthy();
    expect(screen.getByText('Operation')).toBeTruthy();
  });
});

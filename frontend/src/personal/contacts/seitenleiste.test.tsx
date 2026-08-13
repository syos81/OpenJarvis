// @vitest-environment jsdom
// J · Die linke Seitenleiste liess sich in der Breite ziehen, aber nicht
// ausblenden. Kleinste passende Ergaenzung: ein Toggle an der macOS-ueblichen
// Stelle — ganz links in der Toolbar.
//
// Keine Designrunde, kein Pixelabgleich. Geprueft wird, dass das Ausblenden
// den Auswahl- und Detailzustand nicht beschaedigt und der Trenner nicht als
// Griff ins Leere stehenbleibt.

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ContactsToolbar } from './workspace/ContactsToolbar';
import { PaneDivider } from './workspace/PaneDivider';

const quelltext = async (datei: string) => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  return fs.readFileSync(path.join(process.cwd(), datei), 'utf8');
};

function toolbar(offen: boolean, onToggle = () => {}) {
  return render(
    <ContactsToolbar
      seitenleisteOffen={offen} onSeitenleiste={onToggle}
      suche="" onSuche={() => {}} onSucheEscape={() => {}}
      anlegenMoeglich onAnlegen={() => {}} onGesperrt={() => {}}
      bearbeitenSichtbar={false} onBearbeiten={() => {}}
      demoModus={false} />,
  );
}

describe('Toggle der Seitenleiste', () => {
  it('nennt den Zustand und die naechste Handlung', () => {
    const { unmount } = toolbar(true);
    const knopf = screen.getByTestId('seitenleiste-toggle');
    expect(knopf).toHaveAttribute('aria-pressed', 'true');
    expect(knopf).toHaveAttribute('aria-label', 'Seitenleiste ausblenden');
    unmount();

    toolbar(false);
    const zu = screen.getByTestId('seitenleiste-toggle');
    expect(zu).toHaveAttribute('aria-pressed', 'false');
    expect(zu).toHaveAttribute('aria-label', 'Seitenleiste einblenden');
  });

  it('meldet den Klick genau einmal', async () => {
    let geklickt = 0;
    toolbar(true, () => { geklickt += 1; });
    await userEvent.click(screen.getByTestId('seitenleiste-toggle'));
    expect(geklickt).toBe(1);
  });

  it('ist ueber die Tastatur erreichbar', () => {
    toolbar(true);
    expect(screen.getByTestId('seitenleiste-toggle').className)
      .toContain('pjc-focusable');
  });
});

describe('Ausgeblendet heisst unsichtbar, nicht aus dem Grid', () => {
  it('haelt die Spuren auf null', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    expect(quelle).toContain('${seitenleisteOffen ? sidebarBreite : 0}px');
  });

  it('nimmt weder Leiste noch Trenner aus dem Grid-Fluss', async () => {
    // Der Fehler, den dieser Test festhaelt (Nutzerbefund 2026-08-13): Das
    // Grid definiert fuenf Spuren fuer fuenf Kinder. Wer eines davon
    // bedingt rendert oder auf `hidden` (display:none) setzt, laesst alle
    // folgenden Kinder eine Spur nach links rutschen — die Liste landete
    // damit in der Nullspur, und nur die Detailspalte blieb stehen.
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    expect(quelle).not.toContain('{seitenleisteOffen && <PaneDivider');
    expect(quelle).not.toContain('{seitenleisteOffen && <ContactsSidebar');
    expect(quelle).not.toContain('hidden={!seitenleisteOffen}');
    // Stattdessen: Platz halten, Sichtbarkeit nehmen.
    expect(quelle).toContain("visibility: seitenleisteOffen ? 'visible' : 'hidden'");
    expect(quelle).toContain('versteckt={!seitenleisteOffen}');
  });

  it('laesst Auswahl und Filter unberuehrt', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    const block = quelle.split('onSeitenleiste={')[1].slice(0, 120);
    // Nur der Schalter kippt — kein setAuswahlId, kein setSidebarAuswahl.
    expect(block).toContain('setSeitenleisteOffen((o) => !o)');
    expect(block).not.toContain('setAuswahlId');
    expect(block).not.toContain('setSidebarAuswahl');
  });
});

describe('Der versteckte Trenner haelt seinen Platz', () => {
  it('bleibt im Layout, ist aber unsichtbar und nicht greifbar', () => {
    const { container } = render(
      <PaneDivider label="Breite der Seitenleiste" wert={200} min={100}
                   max={300} onChange={() => {}} versteckt />);
    const trenner = container.querySelector('[role="separator"]')!;
    expect(getComputedStyle(trenner).visibility).toBe('hidden');
    expect(trenner.getAttribute('tabindex')).toBe('-1');
    expect(trenner.getAttribute('aria-hidden')).toBe('true');
  });

  it('ist sichtbar und bedienbar, solange die Spalte offen ist', () => {
    const { container } = render(
      <PaneDivider label="Breite der Seitenleiste" wert={200} min={100}
                   max={300} onChange={() => {}} />);
    const trenner = container.querySelector('[role="separator"]')!;
    expect(getComputedStyle(trenner).visibility).toBe('visible');
    expect(trenner.getAttribute('tabindex')).toBe('0');
    expect(trenner.getAttribute('aria-hidden')).toBeNull();
  });
});

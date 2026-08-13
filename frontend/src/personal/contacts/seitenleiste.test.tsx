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

describe('Ausgeblendet heisst weg, nicht abgeraeumt', () => {
  it('haelt Leiste und Trenner beide auf null', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    expect(quelle).toContain('${seitenleisteOffen ? sidebarBreite : 0}px');
    // Ein stehengebliebener Trenner waere ein Griff ins Leere.
    expect(quelle).toContain('{seitenleisteOffen && <PaneDivider');
  });

  it('baut die Leiste nicht neu auf', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    // `hidden` statt Aushaengen: sonst verloere sie ihren Zustand.
    expect(quelle).toContain('hidden={!seitenleisteOffen}');
    expect(quelle).not.toContain('{seitenleisteOffen && <ContactsSidebar');
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

// @vitest-environment jsdom
// A · Der Zielablageort ist Bestandteil der informierten Eigentümerfreigabe.
//
// Vor der Reparatur nannte die Vorschau den Zielcontainer nicht sichtbar: Für
// `update` und `delete` stand im Backend fest `None`, und weder das
// Freigabe-Board noch die Vorgangsansicht zeigten einen Ablageort. Wer
// freigab, sah *was* geschieht, aber nicht *wohin*.
//
// Geprüft wird beides: die Darstellung selbst und dass sie an der Stelle
// steht, an der entschieden wird — der Knopf ohne die Angabe daneben wäre
// wieder eine uninformierte Zustimmung.

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { CONTAINER_ART, Zielangabe } from './components';

const quelltext = async (datei: string) => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  return fs.readFileSync(path.join(process.cwd(), datei), 'utf8');
};

describe('Zielangabe', () => {
  it('nennt Operation, Ziel, Name, Art, Anzahl und stabile Kennung', () => {
    render(<Zielangabe command="delete" targetLabel="Quirin Quasiecht"
                       containerRef="C-4b8df1" containerType="local"
                       containerName="Auf meinem Mac"
                       containerContactCount={4} />);
    const block = screen.getByTestId('zielangabe');
    expect(block.textContent).toContain('Löschen');
    expect(block.textContent).toContain('Quirin Quasiecht');
    // Der Name zuerst — daran erkennt ein Mensch, wohin geschrieben wird.
    expect(block.textContent).toContain('Auf meinem Mac');
    expect(block.textContent).toContain(CONTAINER_ART.local);
    expect(block.textContent).toContain('4 Kontakte');
    // Die Kennung steht zusaetzlich, nie allein.
    expect(block.textContent).toContain('C-4b8df1');
  });

  it('sagt beim fehlenden Namen, dass er fehlt', () => {
    render(<Zielangabe command="create" containerRef="C-4b8df1"
                       containerType="cardDAV" containerName={null}
                       containerContactCount={114} />);
    const block = screen.getByTestId('zielangabe');
    expect(block.textContent).toContain('noch nicht gelesen');
    // Der Notbehelf steht daneben, nicht an der Stelle des Namens.
    expect(block.textContent).toContain('C-4b8df1');
  });

  it('unterscheidet leeres Konto und leeren lokalen Ablageort', () => {
    const { unmount } = render(
      <Zielangabe command="create" containerRef="C-1" containerType="cardDAV"
                  containerName="iCloud" containerContactCount={0} />);
    const konto = screen.getByTestId('zielangabe-art').textContent;
    unmount();

    render(<Zielangabe command="create" containerRef="C-2" containerType="local"
                       containerName="Auf meinem Mac" containerContactCount={0} />);
    expect(screen.getByTestId('zielangabe-art').textContent).not.toBe(konto);
  });

  it('unterscheidet den lokalen Ablageort von einem Konto', () => {
    const { unmount } = render(
      <Zielangabe command="create" containerRef="C-1" containerType="local" />);
    expect(screen.getByTestId('zielangabe').textContent)
      .toContain('Auf meinem Mac');
    unmount();

    render(<Zielangabe command="create" containerRef="C-2"
                       containerType="cardDAV" />);
    expect(screen.getByTestId('zielangabe').textContent)
      .toContain('CardDAV / iCloud');
  });

  it('behauptet keinen Ablageort, wenn keiner bestimmbar ist', () => {
    render(<Zielangabe command="update" containerRef={null}
                       containerType="unknown" />);
    expect(screen.getByTestId('zielangabe').textContent)
      .toContain('nicht bestimmbar');
  });

  it('kennt jede Art des geschlossenen Vorrats', () => {
    // Wortgleich mit `SPECIFIC_CONTAINER_TYPES` im Kern; ein Statiktest auf
    // der Python-Seite hält beide Seiten deckungsgleich.
    for (const art of ['local', 'cardDAV', 'exchange', 'unassigned', 'unknown']) {
      expect(CONTAINER_ART[art]).toBeTruthy();
    }
  });
});

describe('Zielangabe steht dort, wo entschieden wird', () => {
  it('im Freigabe-Board, vor den Entscheidungsknöpfen', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/status/ContactsStatusSurface.tsx');
    const board = quelle.split('function ApprovalBoard')[1]
      .split('function ')[0];
    expect(board).toContain('<Zielangabe');
    // Reihenfolge ist hier die Aussage: erst sehen, dann entscheiden.
    expect(board.indexOf('<Zielangabe'))
      .toBeLessThan(board.indexOf('data-testid="freigabe-freigeben"'));
  });

  it('in der Vorgangsansicht, vor dem Ausführungsknopf', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/status/ContactsStatusSurface.tsx');
    const ansicht = quelle.split('function MutationDetailView')[1];
    expect(ansicht).toContain('<Zielangabe');
    expect(ansicht.indexOf('<Zielangabe'))
      .toBeLessThan(ansicht.indexOf('data-testid="ausfuehren"'));
  });

  it('führt die Beschriftungstabelle genau einmal', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/editor/dialogs.tsx');
    // Der Anlage-Dialog hatte sie zuerst; seit die Freigabevorschau sie
    // ebenfalls braucht, importiert er sie, statt sie zu wiederholen.
    expect(quelle).not.toContain('const CONTAINER_ART');
    expect(quelle).toContain('CONTAINER_ART');
  });
});

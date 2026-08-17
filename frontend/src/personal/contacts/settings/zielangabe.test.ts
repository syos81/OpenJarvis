// Wie der Zielablageort auf der Freigabefläche steht.
//
// Die Fläche ist die produktive Vorschau: Was hier falsch steht, gibt Lukas
// frei, ohne es gemeint zu haben.

import { describe, expect, it } from 'vitest';

import { CONTAINER_ART, zielangabe } from './zielangabe';

describe('Zielangabe', () => {
  it('nennt Name, Art und Anzahl, wenn alles bekannt ist', () => {
    const z = zielangabe('iCloud', 'cardDAV', 'C-1', 114);
    expect(z.name).toBe('iCloud');
    expect(z.artText).toBe(CONTAINER_ART.cardDAV);
    expect(z.anzahlText).toBe('114 Kontakte');
    expect(z.kennung).toBe('C-1');
    expect(z.nameFehltHinweis).toBeNull();
  });

  it('sagt beim fehlenden Namen, dass er fehlt — und setzt nicht die Kennung ein', () => {
    const z = zielangabe(null, 'cardDAV', 'C-1', 114);
    expect(z.name).toBeNull();
    expect(z.nameFehltHinweis).toContain('noch nicht gelesen');
    // Der Notbehelf steht daneben, nicht an der Stelle des Namens.
    expect(z.kennung).toBe('C-1');
    expect(z.nameFehltHinweis).not.toContain('C-1');
  });

  it('unterscheidet Konto und lokalen Ablageort auch bei null Kontakten', () => {
    const konto = zielangabe('iCloud', 'cardDAV', 'C-1', 0);
    const lokal = zielangabe('Auf meinem Mac', 'local', 'C-2', 0);

    expect(konto.istKonto).toBe(true);
    expect(lokal.istKonto).toBe(false);
    expect(konto.artText).not.toBe(lokal.artText);
    // Beide zeigen dieselbe Zahl — die Kategorie kommt nicht von ihr.
    expect(konto.anzahlText).toBe('0 Kontakte');
    expect(lokal.anzahlText).toBe('0 Kontakte');
  });

  it('leitet die Kategorie nie aus der Anzahl ab', () => {
    // Ein volles lokales Verzeichnis bleibt lokal, ein leeres Konto ein Konto.
    expect(zielangabe('Mac', 'local', 'C-2', 9999).istKonto).toBe(false);
    expect(zielangabe('Neu', 'cardDAV', 'C-3', 0).istKonto).toBe(true);
  });

  it('benennt die Art und behauptet keine Gefahr', () => {
    for (const art of ['local', 'cardDAV', 'exchange', 'unassigned', 'unknown']) {
      const text = zielangabe('X', art, 'C', 1).artText;
      for (const dramatik of ['Achtung', 'Warnung', 'Gefahr', 'unwiderruflich']) {
        expect(text).not.toContain(dramatik);
      }
    }
  });

  it('faellt bei unbekannter Art auf eine ehrliche Aussage zurueck', () => {
    const z = zielangabe(null, 'etwas-neues', 'C-9', null);
    expect(z.artText).toBe(CONTAINER_ART.unknown);
    expect(z.istKonto).toBe(false);
    expect(z.anzahlText).toBeNull();
  });

  it('setzt den Singular richtig', () => {
    expect(zielangabe('X', 'local', 'C', 1).anzahlText).toBe('1 Kontakt');
  });
});

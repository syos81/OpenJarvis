// @vitest-environment jsdom
// C · Ein freigegebener, nicht ausgeführter Vorgang darf nicht verschwinden.
//
// Vorher erschien er in keiner Liste: Die Freigabeliste filtert auf
// `awaiting_approval`, und `AUFMERKSAMKEIT` — die Menge hinter dem
// Vorgänge-Reiter — enthielt weder `approved` noch `prepared`. Die
// Detailansicht mit „Jetzt ausführen" existierte, war aber ohne bekannte
// `mutation_id` nicht erreichbar.

import { describe, expect, it } from 'vitest';
import {
  braucht_aufmerksamkeit, gehoert_in_die_vorgangsliste, ist_offen,
} from './status/ContactsStatusSurface';

const quelltext = async (datei: string) => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  return fs.readFileSync(path.join(process.cwd(), datei), 'utf8');
};

describe('Offene Vorgänge', () => {
  it('zählt freigegeben und vorbereitet als offen', () => {
    for (const s of ['prepared', 'awaiting_approval', 'approved']) {
      expect(ist_offen(s)).toBe(true);
      expect(gehoert_in_die_vorgangsliste(s)).toBe(true);
    }
  });

  it('hält offen und klemmt auseinander', () => {
    // Das eine wartet auf eine Entscheidung, das andere braucht Diagnose.
    // Zusammengeworfen ginge genau dieser Unterschied verloren.
    expect(braucht_aufmerksamkeit('approved')).toBe(false);
    expect(ist_offen('outcome_unknown')).toBe(false);
    expect(gehoert_in_die_vorgangsliste('outcome_unknown')).toBe(true);
  });

  it('lässt abgeschlossene Vorgänge aus der Liste', () => {
    for (const s of ['succeeded', 'rejected', 'cancelled', 'expired']) {
      expect(gehoert_in_die_vorgangsliste(s)).toBe(false);
    }
  });

  it('filtert Liste und Reiter über dieselbe Regel', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/status/ContactsStatusSurface.tsx');
    const treffer = quelle.match(/gehoert_in_die_vorgangsliste\(m\.state\)/g);
    // Einmal in der Liste, einmal für die Sichtbarkeit des Reiters. Zwei
    // verschiedene Regeln hiessen: der Reiter fehlt, obwohl es etwas zu
    // sehen gäbe — oder umgekehrt.
    expect(treffer).toHaveLength(2);
  });
});

describe('Der freigegebene Vorgang zeigt, was zu wissen ist', () => {
  it('nennt Frist, Ausführung und Rückweg', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/status/ContactsStatusSurface.tsx');
    const karte = quelle.split("{m.state === 'approved' && (")[1].slice(0, 4200);
    expect(karte).toContain('Freigegeben — noch nicht ausgeführt');
    expect(karte).toContain('data-testid="freigabe-frist"');
    expect(karte).toContain('data-testid="ausfuehren"');
    expect(karte).toContain('data-testid="vorgang-verwerfen"');
  });

  it('führt nichts allein durch die Freigabe aus', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/status/ContactsStatusSurface.tsx');
    // Ausführen haengt an einem eigenen Klick, nicht an einem Effekt.
    const karte = quelle.split("{m.state === 'approved' && (")[1].slice(0, 4200);
    expect(karte).toContain('onClick={async () => {');
    expect(karte).not.toContain('useEffect');
  });
});

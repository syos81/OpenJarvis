// Jarvis Core v0 — Auflösung der Leseaufträge des Routers.
//
// Der Router entscheidet, WAS gelesen wird; diese Datei führt es über den
// `CoreReadPort` aus und macht daraus wieder Zeilen für dieselbe Anzeige.
// Es entsteht kein zweites UI-System: das Ergebnis ist ein ganz normales
// `CoreResult`.
//
// Drei Regeln, die hier hart sind:
//  1. Ein Ausfall der Quelle sieht NIE aus wie ein leeres Ergebnis.
//  2. Mehrdeutige Kontaktsuchen werden nicht auf einen Treffer verengt;
//     die Bar zeigt die Treffer und sagt, wenn es mehr gibt.
//  3. Es wird nichts geschrieben und kein Sync ausgelöst — der Port
//     kennt dafür schlicht keine Operation.

import type { CoreReadRequest, CoreResult } from './commandRouter';
import {
  LeseQuelleNichtErreichbar,
  type CoreReadPort,
  type TerminTreffer,
} from './readPort';

/** Ein UTC-Tagesfenster [00:00, 24:00) für einen lokalen Kalendertag. */
export function tagesFenster(tag: string, jetzt: Date): {
  startUtc: string; endeUtc: string; datum: string;
} {
  const basis = new Date(jetzt);
  if (tag === 'morgen') basis.setDate(basis.getDate() + 1);
  const datum = /^\d{4}-\d{2}-\d{2}$/.test(tag)
    ? tag
    : `${basis.getFullYear()}-${String(basis.getMonth() + 1).padStart(2, '0')}`
      + `-${String(basis.getDate()).padStart(2, '0')}`;
  // Lokale Mitternacht bis lokale Mitternacht des Folgetags, als Instants.
  const [j, m, t] = datum.split('-').map(Number);
  const start = new Date(j, m - 1, t, 0, 0, 0, 0);
  const ende = new Date(j, m - 1, t + 1, 0, 0, 0, 0);
  const iso = (d: Date) => `${d.toISOString().slice(0, 19)}Z`;
  return { startUtc: iso(start), endeUtc: iso(ende), datum };
}

/** Uhrzeit eines Instants in der lokalen Zone — reine Anzeige. */
function uhrzeit(iso: string): string {
  return new Date(iso).toLocaleTimeString('de-DE', {
    hour: '2-digit', minute: '2-digit',
  });
}

function terminZeile(t: TerminTreffer): string {
  const wann = t.ganztaegig
    ? 'ganztägig'
    : `${uhrzeit(t.startUtc)}–${uhrzeit(t.endeUtc)}`;
  return `${wann} · ${t.titel ?? 'Ohne Titel'} · ${t.kalender}`;
}

/** Die sichtbare Ansage bei nicht erreichbarer lokaler Quelle. */
function nichtErreichbar(bereich: 'kontakte' | 'termine',
                         command: string): CoreResult {
  const was = bereich === 'kontakte' ? 'Kontakte' : 'Termine';
  return {
    kind: 'unknown',
    command,
    lines: [
      `${was} sind derzeit nicht verfügbar.`,
      'Das lokale Jarvis-Backend ist nicht erreichbar.',
      'Die übrigen lokalen Befehle funktionieren weiterhin.',
    ],
  };
}

/**
 * Führt einen Leseauftrag aus und liefert das anzuzeigende Ergebnis.
 *
 * Wirft nicht: auch der Ausfall wird zu sichtbaren Zeilen. Das ist der
 * Grund, warum die Bar keinen eigenen Fehlerzustand braucht.
 */
export async function resolveRead(auftrag: CoreReadRequest, port: CoreReadPort,
                                  jetzt: Date = new Date()): Promise<CoreResult> {
  if (auftrag.art === 'kontakte') {
    try {
      const ergebnis = await port.sucheKontakte(auftrag.query, auftrag.limit);
      if (ergebnis.treffer.length === 0) {
        return {
          kind: 'read',
          command: 'kontakt',
          lines: [`Keine Kontakte zu „${auftrag.query}" gefunden.`],
        };
      }
      const zeilen = ergebnis.treffer.map((k) => {
        const org = k.organisation ? ` · ${k.organisation}` : '';
        // Zähler statt Werte — der Core zeigt keine Mailadresse und keine
        // Telefonnummer an.
        const felder = `${k.emailAnzahl} E-Mail, ${k.telefonAnzahl} Tel.`;
        return `${k.name}${org} (${felder})`;
      });
      // Mehrdeutigkeit wird benannt, nicht aufgelöst.
      const kopf = ergebnis.treffer.length === 1
        ? `1 Treffer zu „${auftrag.query}":`
        : `${ergebnis.treffer.length} Treffer zu „${auftrag.query}":`;
      const fuss = ergebnis.weitereVorhanden
        ? ['Es gibt weitere Treffer — Suche eingrenzen.'] : [];
      return {
        kind: 'read', command: 'kontakt',
        lines: [kopf, ...zeilen, ...fuss],
      };
    } catch (fehler) {
      if (fehler instanceof LeseQuelleNichtErreichbar) {
        return nichtErreichbar('kontakte', 'kontakt');
      }
      throw fehler;
    }
  }

  const { startUtc, endeUtc, datum } = tagesFenster(auftrag.tag, jetzt);
  try {
    const termine = await port.ladeTermine(startUtc, endeUtc);
    if (termine.length === 0) {
      return {
        kind: 'read', command: 'termine',
        lines: [`Keine Termine am ${datum}.`],
      };
    }
    const sortiert = [...termine].sort((a, b) =>
      a.startUtc < b.startUtc ? -1 : a.startUtc > b.startUtc ? 1 : 0);
    return {
      kind: 'read', command: 'termine',
      lines: [
        `${sortiert.length} Termin(e) am ${datum}:`,
        ...sortiert.map(terminZeile),
      ],
    };
  } catch (fehler) {
    if (fehler instanceof LeseQuelleNichtErreichbar) {
      return nichtErreichbar('termine', 'termine');
    }
    throw fehler;
  }
}

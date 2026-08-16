// Jarvis Core v0 — Auflösung der Schreibaufträge (Risk Lane).
//
// Hier liegt die Freigabemechanik des Cores, und sie ist bewusst klein:
//
//  · `prepare` legt GENAU EINE offene Vorbereitung ab und zeigt deren
//    Vorschau samt Kennung. Es mutiert nichts.
//  · `execute` ist nur mit der Kennung dieser einen Vorbereitung möglich.
//    Eine falsche Kennung führt nichts aus — auch dann nicht, wenn eine
//    andere Vorbereitung offen ist.
//  · Nach der Ausführung ist die Vorbereitung VERBRAUCHT. Dieselbe
//    Freigabe ein zweites Mal einzugeben, führt nichts aus.
//
// Damit gibt es keine Sammelfreigabe, keine Auto-Approval und keinen Weg,
// auf dem ein Lese- oder Anzeigebefehl eine Mutation auslöst: die einzige
// Eingabe, die `execute` erzeugen kann, ist `freigabe <id>`.

import type { CoreResult, CoreWriteRequest } from './commandRouter';
import {
  SchreibFehler,
  type CoreWritePort, type VorbereiteteMutation,
} from './writePort';

/** Der Zustand zwischen Vorbereiten und Freigeben. Genau ein Platz. */
export interface FreigabeSchacht {
  offen: VorbereiteteMutation | null;
}

export function neuerSchacht(): FreigabeSchacht {
  return { offen: null };
}

/** Deutsche Ansage je Fehlerklasse. Kein Rohtext, keine PII. */
const FEHLER_TEXT: Record<string, string> = {
  operation_nicht_freigeschaltet:
    'Diese Operation ist auf diesem Rechner nicht freigeschaltet — der '
    + 'Server hat sie abgelehnt, bevor irgendetwas vorbereitet wurde.',
  quelle_nicht_erreichbar:
    'Das lokale Jarvis-Backend ist nicht erreichbar — es wurde nichts geändert.',
  keine_berechtigung:
    'Die Berechtigung fehlt — es wurde nichts geändert.',
  ziel_nicht_gefunden:
    'Kein passendes Ziel gefunden — es wurde nichts geändert.',
  ziel_mehrdeutig:
    'Mehrere Treffer — bitte eindeutiger suchen. Es wurde nichts geändert '
    + 'und nichts ausgewählt.',
  ziel_veraendert:
    'Das Ziel hat sich seit der Vorschau geändert — abgebrochen. Bitte neu '
    + 'vorbereiten und neu freigeben.',
  container_nicht_verfuegbar:
    'Kein eindeutiger Zielort verfügbar — es wurde nichts geändert.',
  freigabe_fehlt: 'Die Freigabe wurde nicht angenommen — nichts ausgeführt.',
  freigabe_gehoert_anderer_operation:
    'Diese Freigabe gehört zu einer anderen Operation — nichts ausgeführt.',
  ausfuehrung_fehlgeschlagen:
    'Die Ausführung ist fehlgeschlagen.',
  readback_widerspricht:
    'Der Readback widerspricht der Erwartung — bitte prüfen.',
};

/**
 * Ein Fehler wird zu Zeilen, die drei Dinge benennen: WAS scheiterte,
 * WARUM, und dass nichts geändert wurde.
 *
 * Der Livebefund vom 2026-08-11 war genau hier: „Die Ausführung ist
 * fehlgeschlagen" behauptete eine Ausführung, die es nie gab, und
 * verschwieg den typisierten Grund des Servers. Beides ist jetzt Pflicht.
 */
function fehlerErgebnis(command: string, fehler: unknown): CoreResult {
  if (fehler instanceof SchreibFehler) {
    const schritt = fehler.phase === 'vorbereiten'
      ? 'Die Vorbereitung ist fehlgeschlagen'
      : 'Die Ausführung ist fehlgeschlagen';
    const grund = FEHLER_TEXT[fehler.art] ?? `Grund: ${fehler.art}.`;
    const zeilen = [`${schritt}: ${fehler.art}`, grund];
    // Der Servergrund wortwoertlich — er ist die eigentliche Auskunft.
    if (fehler.detail) zeilen.push(`Server: ${fehler.detail}`);
    if (fehler.serverCode && fehler.serverCode !== fehler.art) {
      zeilen.push(`Servercode: ${fehler.serverCode}`);
    }
    zeilen.push(fehler.phase === 'vorbereiten'
      ? 'Es wurde nichts vorbereitet und nichts geändert.'
      : 'Es wurde nichts geändert, solange kein Sendeversuch gemeldet wurde.');
    return { kind: 'unknown', command, lines: zeilen };
  }
  return {
    kind: 'unknown', command,
    lines: ['Unerwarteter Fehler — es wurde nichts geändert.'],
  };
}

/**
 * Führt einen Schreibauftrag aus — oder bereitet ihn vor.
 *
 * Wirft nicht: jeder Fehler wird zu sichtbaren Zeilen. Eine verletzte
 * Sicherheitsbedingung endet immer ohne Mutation.
 */
export async function resolveWrite(auftrag: CoreWriteRequest,
                                   port: CoreWritePort,
                                   schacht: FreigabeSchacht,
                                   entscheider: string): Promise<CoreResult> {
  if (auftrag.phase === 'abort') {
    schacht.offen = null;
    return { kind: 'write_execute', command: 'abbrechen',
             lines: ['Vorbereitete Mutation verworfen. Es wurde nichts geändert.'] };
  }

  if (auftrag.phase === 'prepare') {
    try {
      const vorbereitet = await vorbereite(auftrag, port);
      // Eine neue Vorbereitung ersetzt die alte — es bleibt bei GENAU
      // EINER offenen Mutation, nie einem Stapel.
      schacht.offen = vorbereitet;
      return {
        kind: 'write_prepare',
        command: vorbereitet.operation,
        lines: [
          ...vorbereitet.vorschau,
          '',
          'Noch ist nichts geändert.',
          `Zum Freigeben:  freigabe ${vorbereitet.mutationId}`,
          `Zum Ausführen:  ausfuehren ${vorbereitet.mutationId}`,
          'Zum Verwerfen:  abbrechen',
        ],
      };
    } catch (fehler) {
      schacht.offen = null;
      return fehlerErgebnis('vorbereiten', fehler);
    }
  }

  // phase === 'approve' | 'execute' — beide verlangen dieselbe Bindung.
  const offen = schacht.offen;
  const kommando = auftrag.phase === 'approve' ? 'freigabe' : 'ausfuehren';
  if (!offen) {
    return {
      kind: 'unknown', command: kommando,
      lines: ['Es liegt keine vorbereitete Mutation vor — nichts ausgeführt.'],
    };
  }
  if (offen.mutationId !== auftrag.mutationId) {
    // Die Bindung: eine Freigabe für A führt B niemals aus.
    return {
      kind: 'unknown', command: kommando,
      lines: [FEHLER_TEXT.freigabe_gehoert_anderer_operation],
    };
  }

  if (auftrag.phase === 'approve') {
    // Freigeben ist ein eigener Schritt und lässt die Vorbereitung offen:
    // ausgeführt wird sie erst durch das zweite Kommando. Der Schacht wird
    // hier NICHT geleert — sonst wäre die Freigabe zugleich ihr Verbrauch.
    try {
      await port.genehmige(offen, entscheider);
    } catch (fehler) {
      return fehlerErgebnis('freigabe', fehler);
    }
    return {
      kind: 'write_execute',
      command: 'freigabe',
      lines: [
        'Freigegeben. Es wurde nichts geändert und nichts gesendet.',
        `Zum Ausführen: ausfuehren ${offen.mutationId}`,
        'Zum Verwerfen: abbrechen',
      ],
    };
  }

  // Verbraucht, BEVOR ausgeführt wird: auch ein Fehlschlag lässt keine
  // zweite Ausführung derselben Freigabe zu.
  schacht.offen = null;
  try {
    const ergebnis = await port.fuehreAus(offen);
    return {
      kind: 'write_execute',
      command: offen.operation,
      lines: [
        ergebnis.readbackBestaetigt
          ? 'Ausgeführt und durch frischen Readback bestätigt:'
          : 'Ausgeführt, aber der Readback bestätigt es NICHT:',
        ...ergebnis.readback,
      ],
    };
  } catch (fehler) {
    return fehlerErgebnis(offen.operation, fehler);
  }
}

/** Die Vorbereitung je Operation — jede über den bewiesenen Fachpfad. */
async function vorbereite(auftrag: Extract<CoreWriteRequest, { phase: 'prepare' }>,
                          port: CoreWritePort): Promise<VorbereiteteMutation> {
  switch (auftrag.operation) {
    case 'kontakt_anlegen':
      return port.bereiteKontaktAnlegenVor(auftrag.ziel, auftrag.name);
    case 'kontakt_aendern': {
      const ziel = await port.findeKontakt(auftrag.query);
      return port.bereiteKontaktAendernVor(ziel, auftrag.feld, auftrag.wert);
    }
    case 'kontakt_loeschen': {
      const ziel = await port.findeKontakt(auftrag.query);
      return port.bereiteKontaktLoeschenVor(ziel);
    }
    case 'termin_anlegen':
      return port.bereiteTerminAnlegenVor(auftrag.ziel, auftrag.titel,
                                          auftrag.tag, auftrag.vonBis);
    case 'termin_aendern': {
      const ziel = await port.findeTermin(auftrag.tag, auftrag.query);
      return port.bereiteTerminAendernVor(ziel, auftrag.neuerTitel);
    }
  }
}

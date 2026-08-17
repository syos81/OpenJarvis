// Fehler-Normalisierung der Kontakte-Oberfläche (aus dem Bestand übernommen).
//
// Der Server liefert Satz, Kategorie, stabile Kennung und Wiederholbarkeit
// getrennt. Wer davon nur `message` weiterreicht, wirft genau die Angaben
// weg, die der Nutzer braucht.

import { ContactsApiError } from '../api';
import { FreigabeAbgelehnt, fehlerText } from '../settings/freigabe';

export interface Fehlerbild {
  message: string;
  code?: string;
  technicalCode?: string;
  retryable?: boolean;
}

export function fehlerbild(e: unknown): Fehlerbild {
  // Eine abgelehnte Einzelfreigabe traegt ihren eigenen, ganzen Satz. Der
  // haeufigste Fall ist eine seit der Handlung veraenderte Vorschau — ohne
  // Erklaerung liest sich der gewollte Abbruch wie ein Defekt.
  if (e instanceof FreigabeAbgelehnt) {
    return {
      message: fehlerText(e.grund),
      technicalCode: e.grund,
      retryable: e.grund === 'preview_changed',
    };
  }
  if (e instanceof ContactsApiError) {
    return {
      message: e.message,
      code: e.code,
      technicalCode: e.technicalCode,
      retryable: e.retryable,
    };
  }
  if (e instanceof Error) {
    return {
      message: 'Der lokale Server war nicht erreichbar.',
      technicalCode: 'network_unreachable',
      retryable: true,
    };
  }
  return { message: 'Unbekannter Fehler.', technicalCode: 'unknown' };
}

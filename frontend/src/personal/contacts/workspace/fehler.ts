// Fehler-Normalisierung der Kontakte-Oberfläche (aus dem Bestand übernommen).
//
// Der Server liefert Satz, Kategorie, stabile Kennung und Wiederholbarkeit
// getrennt. Wer davon nur `message` weiterreicht, wirft genau die Angaben
// weg, die der Nutzer braucht.

import { ContactsApiError } from '../api';

export interface Fehlerbild {
  message: string;
  code?: string;
  technicalCode?: string;
  retryable?: boolean;
}

export function fehlerbild(e: unknown): Fehlerbild {
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

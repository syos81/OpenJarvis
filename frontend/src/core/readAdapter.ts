// Jarvis Core v0 — der Rand zwischen Core und den Fachmodulen.
//
// Dies ist die einzige Datei des Cores, die die Kontakte- und
// Kalendermodule überhaupt importiert. Sie verengt deren breitere
// Schnittstellen auf `CoreReadPort`: hereingereicht werden ausschliesslich
// die beiden bereits bewiesenen LESEfunktionen
//
//   contacts.listContacts({ search, limit })   GET  …/contacts
//   calendar.ladeTermine(start, ende)          GET  …/calendar/events
//
// Beide laufen über den lokalen Jarvis-Server auf 127.0.0.1 — kein
// externer Dienst, kein Connector, kein Cloud-Aufruf. Ein Sync wird
// bewusst NICHT ausgelöst: gelesen wird der gespeicherte Bestand, wie ihn
// die bestehenden Ansichten auch lesen.
//
// Was hier NICHT steht, ist die eigentliche Aussage: kein `prepare…`,
// kein `approve`, kein `execute`, kein `runSync`. Der Core bekommt keinen
// Mutationspfad — auch keinen versehentlichen.

import { listContacts } from '../personal/contacts/api';
import { ladeTermine as ladeTermineApi } from '../personal/calendar/api';
import {
  LeseQuelleNichtErreichbar,
  type CoreReadPort,
  type KontaktErgebnis,
  type TerminTreffer,
} from './readPort';

/**
 * Der produktive Lese-Port über die bestehenden lokalen Lesewege.
 *
 * Jeder Fehler der Quelle — Backend aus, Verbindung verweigert, unlesbare
 * Antwort — wird zu `LeseQuelleNichtErreichbar`. Er wird nicht zu einer
 * leeren Trefferliste: ein ausgefallener Lesepfad darf nie wie „nichts
 * gefunden" aussehen.
 */
export function produktiverReadPort(): CoreReadPort {
  return {
    async sucheKontakte(query: string, limit: number): Promise<KontaktErgebnis> {
      let seite;
      try {
        seite = await listContacts({ search: query, limit });
      } catch (fehler) {
        throw new LeseQuelleNichtErreichbar('kontakte', fehler);
      }
      return {
        treffer: seite.items.map((k) => ({
          id: k.id,
          name: k.display_name,
          organisation: k.organization_name,
          // Zähler statt Werte: der Core lädt keine Mailadressen und keine
          // Telefonnummern und zeigt sie folglich auch nicht.
          emailAnzahl: k.email_count,
          telefonAnzahl: k.phone_count,
        })),
        weitereVorhanden: seite.has_more,
      };
    },

    async ladeTermine(startUtc: string, endeUtc: string): Promise<readonly TerminTreffer[]> {
      let fenster;
      try {
        fenster = await ladeTermineApi(startUtc, endeUtc);
      } catch (fehler) {
        throw new LeseQuelleNichtErreichbar('termine', fehler);
      }
      return fenster.events.map((t) => ({
        id: t.id,
        titel: t.title,
        startUtc: t.starts_at_utc,
        endeUtc: t.ends_at_utc,
        ganztaegig: t.is_all_day,
        kalender: t.calendar_name,
      }));
    },
  };
}

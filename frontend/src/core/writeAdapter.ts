// Jarvis Core v0 — der Rand zwischen Core und den bewiesenen Schreibpfaden.
//
// Diese Datei baut KEINEN zweiten Schreibstack. Sie reicht die bereits
// produktiv bewiesenen Abläufe durch und hält deren Schritte getrennt:
//
//   Kontakte  prepare… → approve → execute        (Server-Kanal)
//   Kalender  bereiteVor/bereiteUpdateVor → gibFrei → beanspruche
//             → fuehreAus (nativ) → schliesseAb   (App-Prozess-Kanal)
//
// Beide binden den Vorzustand selbst: Kontakte über `expected_revision`,
// der Kalender über den `expected_fingerprint`, den der native Pfad
// unmittelbar vor der Mutation gegen einen frischen Read hält. Genau
// deshalb wird hier nichts nachgebaut — ein zweiter Fingerprint wäre eine
// zweite Wahrheit.
//
// Was hier NICHT steht, ist die Aussage: kein `bereiteLoeschenVor`, kein
// `erhebeLoeschProbe`, kein Kalender-DELETE in irgendeiner Form. Der Core
// erreicht ihn nicht — auch nicht versehentlich.

import {
  approveMutation, executeMutation, getContact, getMutation, listContacts,
  listContainers, prepareCreate, prepareDelete, prepareUpdate,
} from '../personal/contacts/api';
import { ladeKalender, ladeTermine as ladeTermineApi } from '../personal/calendar/api';
import {
  beanspruche, bereiteUpdateVor, bereiteVor, fuehreAus as fuehreNativAus,
  gibFrei, ladeMutation, schliesseAb,
} from '../personal/calendar/mutationsApi';
import { tagesFenster } from './readResolver';
import {
  SchreibFehler,
  type AusgefuehrteMutation, type CoreWritePort, type VorbereiteteMutation,
  type Zielobjekt,
} from './writePort';

/** Die Felder, die `kontakt-aendern` setzen darf. Bewusst klein und
 *  geschlossen: was hier nicht steht, ist aus dem Core nicht änderbar. */
export const AENDERBARE_KONTAKTFELDER = [
  'organisation', 'position', 'spitzname',
] as const;

const FELD_ABBILDUNG: Record<string, string> = {
  organisation: 'organization_name',
  position: 'job_title',
  spitzname: 'nickname',
};

function neueId(): string {
  return globalThis.crypto?.randomUUID?.()
    ?? `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Jeder Fehler der Quelle wird zu einer benannten Klasse — nie zu einem
 *  stillen Weiterlaufen, nie zu einem leeren Ergebnis und nie zu einem
 *  Text, der den Grund verschweigt.
 *
 *  Livebefund 2026-08-11: der erste Versuch meldete „Die Ausfuehrung ist
 *  fehlgeschlagen", obwohl (a) nichts ausgefuehrt wurde und (b) der Server
 *  einen typisierten Grund mitgeschickt hatte (`unsupported`,
 *  „Operation 'create' ist nicht deklariert"). Beides wird hier
 *  ausgewertet statt weggeworfen: der Servercode entscheidet die Klasse,
 *  die Phase entscheidet die Wortwahl. */
function alsSchreibFehler(fehler: unknown, standard: SchreibFehler): never {
  const phase = standard.phase;
  // Der typisierte Servercode hat Vorrang vor jeder Textheuristik.
  const code = (fehler as { code?: unknown })?.code;
  const status = (fehler as { status?: unknown })?.status;
  const serverCode = typeof code === 'string' ? code : undefined;
  if (serverCode === 'unsupported') {
    throw new SchreibFehler('operation_nicht_freigeschaltet',
                            (fehler as Error)?.message, phase, serverCode);
  }
  if (serverCode === 'conflict' || status === 409) {
    throw new SchreibFehler('ziel_veraendert', undefined, phase, serverCode);
  }
  if (serverCode === 'forbidden' || status === 403) {
    throw new SchreibFehler('keine_berechtigung', undefined, phase, serverCode);
  }
  if (serverCode === 'not_found' || status === 404) {
    throw new SchreibFehler('ziel_nicht_gefunden', undefined, phase, serverCode);
  }
  if (typeof status === 'number' && status >= 500) {
    throw new SchreibFehler('quelle_nicht_erreichbar', undefined, phase,
                            serverCode);
  }
  // Kein Status: der Aufruf kam gar nicht erst an (WebKit meldet das je
  // nach Lage als „Load failed" oder „Failed to fetch").
  if (status === undefined && fehler instanceof Error) {
    throw new SchreibFehler('quelle_nicht_erreichbar', undefined, phase,
                            serverCode);
  }
  // Alles Uebrige: die Klasse des Aufrufers, aber MIT dem Servergrund.
  throw new SchreibFehler(standard.art, (fehler as Error)?.message, phase,
                          serverCode);
}

export function produktiverWritePort(): CoreWritePort {
  /** Genau ein Treffer, oder ein benannter Fehler. Es wird NIE geraten. */
  const einKontakt = async (query: string): Promise<Zielobjekt> => {
    let seite;
    try {
      seite = await listContacts({ search: query, limit: 5 });
    } catch (f) {
      alsSchreibFehler(f, new SchreibFehler('quelle_nicht_erreichbar',
          undefined, 'vorbereiten'));
    }
    if (seite.items.length === 0) throw new SchreibFehler('ziel_nicht_gefunden');
    if (seite.items.length > 1 || seite.has_more) {
      // Mehrdeutigkeit wird gemeldet, nicht aufgelöst.
      throw new SchreibFehler('ziel_mehrdeutig',
                              `${seite.items.length}${seite.has_more ? '+' : ''}`);
    }
    const k = seite.items[0];
    return { id: k.id, bezeichnung: k.display_name, container: null };
  };

  const einTermin = async (tag: string, query: string): Promise<Zielobjekt> => {
    const { startUtc, endeUtc } = tagesFenster(tag, new Date());
    let fenster;
    try {
      fenster = await ladeTermineApi(startUtc, endeUtc);
    } catch (f) {
      alsSchreibFehler(f, new SchreibFehler('quelle_nicht_erreichbar',
          undefined, 'vorbereiten'));
    }
    const suche = query.trim().toLowerCase();
    const treffer = fenster.events.filter(
      (t) => (t.title ?? '').toLowerCase().includes(suche));
    if (treffer.length === 0) throw new SchreibFehler('ziel_nicht_gefunden');
    if (treffer.length > 1) {
      throw new SchreibFehler('ziel_mehrdeutig', String(treffer.length));
    }
    const t = treffer[0];
    return {
      id: t.provider_event_id,
      bezeichnung: t.title ?? 'Ohne Titel',
      container: t.provider_calendar_id,
    };
  };

  /** Der Zielcontainer wird AUSDRUECKLICH benannt und muss dann eindeutig
   *  treffen. Auf diesem Mac existieren mehrere — der Core waehlt nie
   *  selbst aus, er verlangt die Auswahl. */
  const einContainer = async (zielName: string): Promise<string> => {
    let container;
    try {
      container = await listContainers();
    } catch (f) {
      alsSchreibFehler(f, new SchreibFehler('quelle_nicht_erreichbar',
          undefined, 'vorbereiten'));
    }
    if (container.length === 0) {
      throw new SchreibFehler('container_nicht_verfuegbar');
    }
    const gesucht = zielName.trim().toLowerCase();
    const treffer = container.filter(
      (c) => c.container_ref.toLowerCase() === gesucht
        || c.container_ref.toLowerCase().includes(gesucht));
    if (treffer.length === 0) {
      throw new SchreibFehler('container_nicht_verfuegbar', zielName);
    }
    if (treffer.length > 1) {
      throw new SchreibFehler('ziel_mehrdeutig', `${treffer.length} Container`);
    }
    return treffer[0].container_ref;
  };

  /** Derselbe Anspruch für den Zielkalender: ausdruecklich benannt,
   *  eindeutig getroffen — sonst fail-closed. */
  const einKalender = async (zielName: string,
  ): Promise<{ id: string; name: string }> => {
    let antwort;
    try {
      antwort = await ladeKalender();
    } catch (f) {
      alsSchreibFehler(f, new SchreibFehler('quelle_nicht_erreichbar',
          undefined, 'vorbereiten'));
    }
    const schreibbar = antwort.calendars.filter((k) => k.is_writable);
    if (schreibbar.length === 0) {
      throw new SchreibFehler('container_nicht_verfuegbar');
    }
    const gesucht = zielName.trim().toLowerCase();
    const genau = schreibbar.filter(
      (k) => k.display_name.toLowerCase() === gesucht);
    const treffer = genau.length > 0
      ? genau
      : schreibbar.filter((k) => k.display_name.toLowerCase().includes(gesucht));
    if (treffer.length === 0) {
      throw new SchreibFehler('container_nicht_verfuegbar', zielName);
    }
    if (treffer.length > 1) {
      throw new SchreibFehler('ziel_mehrdeutig', `${treffer.length} Kalender`);
    }
    return { id: treffer[0].provider_calendar_id,
             name: treffer[0].display_name };
  };

  return {
    findeKontakt: einKontakt,
    findeTermin: einTermin,

    async bereiteKontaktAnlegenVor(zielName: string, name: string,
    ): Promise<VorbereiteteMutation> {
      const containerRef = await einContainer(zielName);
      const teile = name.trim().split(/\s+/);
      const fields = {
        contact_type: 'person' as const,
        given_name: teile[0],
        ...(teile.length > 1 ? { family_name: teile.slice(1).join(' ') } : {}),
      };
      let vorbereitet;
      try {
        vorbereitet = await prepareCreate({
          containerRef, fields,
          idempotencyKey: neueId(), correlationId: neueId(),
        });
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      return {
        operation: 'kontakt_anlegen',
        mutationId: vorbereitet.mutation_id,
        kanal: 'kontakte',
        gebundenerZustand: null,
        ziel: null,
        vorschau: [
          'Operation: Kontakt anlegen',
          `Zielcontainer: ${containerRef}`,
          `Anzulegen: ${name.trim()}`,
        ],
      };
    },

    async bereiteKontaktAendernVor(ziel, feld, wert) {
      const schluessel = FELD_ABBILDUNG[feld];
      if (!schluessel) throw new SchreibFehler('ziel_nicht_gefunden', feld);
      // Frischer Read UNMITTELBAR vor der Vorschau — daraus stammt die
      // Revision, die die Freigabe bindet.
      let detail;
      try {
        detail = await getContact(ziel.id);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ziel_nicht_gefunden',
          undefined, 'vorbereiten'));
      }
      const vorher = (detail as unknown as Record<string, unknown>)[schluessel];
      let vorbereitet;
      try {
        vorbereitet = await prepareUpdate(ziel.id, {
          expectedRevision: detail.revision,
          fields: { [schluessel]: wert },
          idempotencyKey: neueId(), correlationId: neueId(),
        });
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      return {
        operation: 'kontakt_aendern',
        mutationId: vorbereitet.mutation_id,
        kanal: 'kontakte',
        gebundenerZustand: detail.revision,
        ziel,
        vorschau: [
          'Operation: Kontakt ändern',
          `Ziel: ${ziel.bezeichnung}`,
          `${feld}: ${vorher ?? '—'} → ${wert}`,
          `Gebundener Vorzustand: Revision ${detail.revision}`,
        ],
      };
    },

    async bereiteKontaktLoeschenVor(ziel) {
      let detail;
      try {
        detail = await getContact(ziel.id);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ziel_nicht_gefunden',
          undefined, 'vorbereiten'));
      }
      let vorbereitet;
      try {
        vorbereitet = await prepareDelete(ziel.id, {
          expectedRevision: detail.revision,
          idempotencyKey: neueId(), correlationId: neueId(),
        });
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      return {
        operation: 'kontakt_loeschen',
        mutationId: vorbereitet.mutation_id,
        kanal: 'kontakte',
        gebundenerZustand: detail.revision,
        ziel,
        vorschau: [
          'Operation: Kontakt LÖSCHEN',
          `Ziel: ${detail.display_name}`,
          `Gebundener Vorzustand: Revision ${detail.revision}`,
          'Dieser Kontakt wird beim Anbieter entfernt.',
        ],
      };
    },

    async bereiteTerminAnlegenVor(zielName, titel, tag, vonBis) {
      const kalender = await einKalender(zielName);
      const [von, bis] = vonBis.split('-');
      if (!/^\d{2}:\d{2}$/.test(von ?? '') || !/^\d{2}:\d{2}$/.test(bis ?? '')) {
        throw new SchreibFehler('ziel_nicht_gefunden', 'zeitformat');
      }
      const { datum } = tagesFenster(tag, new Date());
      const instant = (zeit: string) => {
        const [j, m, t] = datum.split('-').map(Number);
        const [h, min] = zeit.split(':').map(Number);
        return `${new Date(j, m - 1, t, h, min, 0, 0).toISOString().slice(0, 19)}Z`;
      };
      const felder = {
        title: titel, starts_at_utc: instant(von), ends_at_utc: instant(bis),
        is_all_day: false, location: null, notes: null,
        time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      };
      if (felder.ends_at_utc <= felder.starts_at_utc) {
        throw new SchreibFehler('ziel_nicht_gefunden', 'ende_vor_beginn');
      }
      let vorbereitet;
      try {
        vorbereitet = await bereiteVor(kalender.id, felder);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      return {
        operation: 'termin_anlegen',
        mutationId: vorbereitet.mutation_id,
        kanal: 'termine',
        gebundenerZustand: null,
        ziel: { id: '', bezeichnung: titel, container: kalender.id },
        vorschau: [
          'Operation: Termin anlegen',
          `Zielkalender: ${kalender.name}`,
          `Titel: ${titel}`,
          `Zeit: ${datum} ${von}–${bis}`,
        ],
      };
    },

    async bereiteTerminAendernVor(ziel, neuerTitel) {
      if (!ziel.container) throw new SchreibFehler('ziel_nicht_gefunden');
      let vorbereitet;
      try {
        // Der Server liest den Vorzustand selbst und bindet den
        // Fingerprint in den Auftrag; der native Pfad prüft ihn
        // unmittelbar vor der Mutation erneut.
        vorbereitet = await bereiteUpdateVor(ziel.container, ziel.id,
                                             { title: neuerTitel });
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      return {
        operation: 'termin_aendern',
        mutationId: vorbereitet.mutation_id,
        kanal: 'termine',
        gebundenerZustand: vorbereitet.payload_digest,
        ziel,
        vorschau: [
          'Operation: Termin ändern',
          `Ziel: ${ziel.bezeichnung}`,
          `Titel: ${ziel.bezeichnung} → ${neuerTitel}`,
          'Der Vorzustand ist gebunden und wird unmittelbar vor der '
          + 'Änderung erneut geprüft.',
        ],
      };
    },

    /**
     * Die Eigentümerfreigabe — und sonst nichts.
     *
     * Beide Kanäle über dieselbe Grenze: der Kern nimmt eine gesiegelte
     * `OwnerDecision` entgegen, die ausschliesslich am interaktiven
     * Freigabe-Endpunkt entsteht. Der Entscheider wird durchgereicht und
     * nicht hier gewählt.
     */
    async genehmige(vorbereitet: VorbereiteteMutation,
                    entscheider: string): Promise<void> {
      try {
        if (vorbereitet.kanal === 'kontakte') {
          await approveMutation(vorbereitet.mutationId, entscheider);
        } else {
          await gibFrei(vorbereitet.mutationId, entscheider);
        }
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('freigabe_fehlt', undefined,
                                              'ausfuehren'));
      }
    },

    async fuehreAus(vorbereitet: VorbereiteteMutation): Promise<AusgefuehrteMutation> {
      if (vorbereitet.kanal === 'kontakte') {
        // **Hier wird nicht freigegeben.** Bis 2026-08-13 stand an dieser
        // Stelle `approveMutation(id, ENTSCHEIDER)` mit einem hartkodierten
        // `'lukas'` — ein vom Produktcode gewählter String ist keine
        // Eigentümerhandlung, und ein Ausführungsschritt, der sich selbst die
        // Freigabe erteilt, hat die Trennung von Vorbereiten und Ausführen
        // aufgehoben (§8 G). Der Kern nimmt seit derselben Änderung nur noch
        // eine gesiegelte `OwnerDecision` entgegen, die ausschliesslich am
        // interaktiven Freigabeweg entsteht.
        //
        // Ausgeführt wird deshalb nur, was der Eigentümer bereits freigegeben
        // hat. Der Zustand wird frisch gelesen statt aus der Vorbereitung
        // erinnert: Zwischen Prepare und Execute kann die Freigabe erteilt,
        // abgelaufen oder verbraucht worden sein.
        let zustand;
        try {
          zustand = await getMutation(vorbereitet.mutationId);
        } catch (f) {
          alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
                                                undefined, 'ausfuehren'));
        }
        // `approval_state` ist der **wirksame** Zustand: Eine erteilte, aber
        // abgelaufene Freigabe liest sich als `expired` und nicht mehr als
        // `granted`. Beide Bedingungen zusammen decken die vier Fälle, in
        // denen nicht ausgeführt werden darf — wartend, abgelaufen,
        // verbraucht, abgeschlossen.
        if (zustand.state !== 'approved' || zustand.approval_state !== 'granted') {
          throw new SchreibFehler('freigabe_fehlt',
                                  zustand.approval_state ?? zustand.state,
                                  'ausfuehren');
        }
        let ergebnis;
        try {
          ergebnis = await executeMutation(vorbereitet.mutationId);
        } catch (f) {
          alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
        }
        if (ergebnis.outcome !== 'succeeded' && ergebnis.state !== 'succeeded') {
          throw new SchreibFehler('ausfuehrung_fehlgeschlagen',
                                  ergebnis.error_code ?? ergebnis.state);
        }
        return leseKontaktZurueck(vorbereitet, ergebnis.contact_id);
      }

      // Kalender: beanspruche → nativer Execute → schliesseAb.
      //
      // **Hier wird nicht freigegeben.** Bis 2026-08-16 stand an dieser Stelle
      // `await gibFrei(...)`, und `gibFrei` setzte einen im Produktcode
      // hartkodierten Entscheider ein. Freigeben und Ausführen fielen damit in
      // denselben Aufruf — dieselbe Defektklasse wie G im Kontaktzweig, nur
      // eine Etage tiefer und drei Tage länger unbemerkt.
      //
      // Der Zustand wird frisch gelesen, nicht aus der Vorbereitung erinnert:
      // Zwischen Vorbereiten und Ausführen kann die Freigabe erteilt,
      // abgelaufen oder verbraucht worden sein.
      let zustand;
      try {
        zustand = await ladeMutation(vorbereitet.mutationId);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'ausfuehren'));
      }
      // `approval_state` ist der **wirksame** Zustand: Eine erteilte, aber
      // abgelaufene Freigabe liest sich als `expired`. Beide Bedingungen
      // zusammen decken die vier Fälle, in denen nicht ausgeführt werden darf
      // — wartend, abgelaufen, verbraucht, abgeschlossen. Der Server prüft
      // dasselbe beim Claim; diese Stelle spart den Fehlversuch und sagt dem
      // Eigentümer, was fehlt.
      if (zustand.state !== 'approved' || zustand.approval_state !== 'granted') {
        throw new SchreibFehler('freigabe_fehlt',
                                zustand.approval_state ?? zustand.state,
                                'ausfuehren');
      }
      let auftrag;
      try {
        auftrag = await beanspruche(vorbereitet.mutationId);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      let bericht;
      try {
        // Der Auftrag geht UNVERÄNDERT hinüber — und höchstens einmal.
        bericht = await fuehreNativAus(JSON.stringify(auftrag));
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      let settle;
      try {
        settle = await schliesseAb(vorbereitet.mutationId, auftrag.claim_token,
                                   bericht);
      } catch (f) {
        alsSchreibFehler(f, new SchreibFehler('ausfuehrung_fehlgeschlagen',
          undefined, 'vorbereiten'));
      }
      if (settle.state !== 'succeeded'
          && settle.state !== 'provider_applied_pending_reconcile') {
        throw new SchreibFehler('ausfuehrung_fehlgeschlagen',
                                settle.error_class ?? settle.state);
      }
      return leseTerminZurueck(vorbereitet, bericht.provider_identifier);
    },
  };

  /** Readback nach einer Kontaktmutation — gelesen, nicht behauptet. */
  async function leseKontaktZurueck(vorbereitet: VorbereiteteMutation,
                                    kontaktId: string | null,
  ): Promise<AusgefuehrteMutation> {
    const id = kontaktId ?? vorbereitet.ziel?.id ?? '';
    if (vorbereitet.operation === 'kontakt_loeschen') {
      // Positive Nichtvorhandenheitskontrolle: das freigegebene Objekt
      // darf nicht mehr auffindbar sein.
      try {
        await getContact(id);
      } catch {
        return {
          operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
          readbackBestaetigt: true,
          readback: [`Gelöscht — ${vorbereitet.ziel?.bezeichnung ?? id} ist `
                     + 'nicht mehr abrufbar.'],
        };
      }
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: false,
        readback: ['Der Kontakt ist nach dem Löschen weiterhin abrufbar — '
                   + 'der Ausgang ist ungewiss.'],
      };
    }
    try {
      const detail = await getContact(id);
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: true,
        readback: [`Gelesen: ${detail.display_name}`,
                   `Revision jetzt: ${detail.revision}`],
      };
    } catch {
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: false,
        readback: ['Die Mutation wurde gemeldet, der Readback ist aber '
                   + 'nicht lesbar — der Ausgang ist ungewiss.'],
      };
    }
  }

  /** Readback nach einer Kalendermutation aus dem gespeicherten Bestand. */
  async function leseTerminZurueck(vorbereitet: VorbereiteteMutation,
                                   kennung: string | null,
  ): Promise<AusgefuehrteMutation> {
    if (!kennung) {
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: false,
        readback: ['Keine Providerkennung gemeldet — der Ausgang ist ungewiss.'],
      };
    }
    const { startUtc, endeUtc } = tagesFenster('heute', new Date());
    try {
      const fenster = await ladeTermineApi(startUtc, endeUtc);
      const treffer = fenster.events.find((t) => t.provider_event_id === kennung);
      if (!treffer) {
        return {
          operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
          readbackBestaetigt: false,
          readback: ['Der Termin ist im gespeicherten Bestand noch nicht '
                     + 'sichtbar — der lokale Abgleich steht aus.'],
        };
      }
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: true,
        readback: [`Gelesen: ${treffer.title ?? 'Ohne Titel'}`,
                   `Kalender: ${treffer.calendar_name}`],
      };
    } catch {
      return {
        operation: vorbereitet.operation, mutationId: vorbereitet.mutationId,
        readbackBestaetigt: false,
        readback: ['Der Readback ist nicht lesbar — der Ausgang ist ungewiss.'],
      };
    }
  }
}

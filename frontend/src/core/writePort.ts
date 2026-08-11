// Jarvis Core v0 — der Schreib-Port des Kerns (Risk Lane).
//
// Wie beim Lese-Port gilt: was hier nicht steht, kann der Core nicht tun.
// Der Port trägt GENAU FÜNF Operationen — und Calendar DELETE ist keine
// davon. Das ist keine Konvention, sondern Typ: es gibt keine Methode, die
// einen Kalendertermin löschen könnte, und keinen Adapter, der eine
// bereitstellt.
//
// Die eigentliche Sicherheit liegt weiter unten in den bereits bewiesenen
// Fachpfaden (prepare → approve → execute bei Kontakten; prepare → approve
// → claim → nativer Execute → settle beim Kalender, mit Re-Read und
// Fingerprintvergleich unmittelbar vor der Mutation). Dieser Port baut
// davon nichts nach — er reicht die Schritte durch und hält sie getrennt.
//
// Drei Trennungen sind hier hart:
//  1. VORBEREITEN und AUSFÜHREN sind zwei Aufrufe. Ein Vorbereiten
//     mutiert nie.
//  2. Zwischen beiden steht die Freigabe des Eigentümers, gebunden an
//     genau diese eine vorbereitete Operation.
//  3. Ein Lesebefehl kann keine dieser Operationen auslösen — der
//     Lese-Port kennt sie nicht.

/** Die geschlossene Menge dessen, was der Core schreiben darf. */
export type WriteOperation =
  | 'kontakt_anlegen'
  | 'kontakt_aendern'
  | 'kontakt_loeschen'
  | 'termin_anlegen'
  | 'termin_aendern';

/** Eine vorbereitete, noch NICHT ausgeführte Mutation.
 *
 * `mutationId` ist die Bindung: die Freigabe gilt genau ihr. Eine Freigabe
 * für A kann B nicht ausführen, und eine Freigabe für ein Update kann kein
 * Löschen autorisieren — die Operation reist mit. */
export interface VorbereiteteMutation {
  readonly operation: WriteOperation;
  readonly mutationId: string;
  /** Welcher Fachkanal die Ausfuehrung traegt. Die beiden haben
   *  unterschiedliche, jeweils bereits bewiesene Ablaeufe — der Port baut
   *  keinen dritten daneben. */
  readonly kanal: 'kontakte' | 'termine';
  /** Die anzuzeigende Vorschau — aus den tatsaechlich gelesenen Werten
   *  gebaut, nicht erfunden. */
  readonly vorschau: readonly string[];
  /** Der Vorzustands-Beleg, den der Server gebunden hat: bei Kontakten die
   *  Revision, beim Kalender der Fingerprint. `null` beim Anlegen, wo es
   *  noch keinen Vorzustand gibt. */
  readonly gebundenerZustand: string | null;
  /** Das aufgeloeste Ziel — fuer den Readback nach der Mutation.
   *  Beim Anlegen erst nach der Ausfuehrung bekannt. */
  readonly ziel: Zielobjekt | null;
}

/** Das Ergebnis einer ausgeführten Mutation samt frischem Readback. */
export interface AusgefuehrteMutation {
  readonly operation: WriteOperation;
  readonly mutationId: string;
  /** Zeilen des Readbacks — was nach der Mutation TATSÄCHLICH gelesen wurde. */
  readonly readback: readonly string[];
  /** `true` nur, wenn der Readback die Erwartung bestätigt hat. */
  readonly readbackBestaetigt: boolean;
}

/** Ein eindeutig bestimmtes Zielobjekt. Mehrdeutigkeit wird NIE hier
 *  aufgelöst — sie ist ein eigener Fehler. */
export interface Zielobjekt {
  readonly id: string;
  readonly bezeichnung: string;
  /** Der Ablageort: Kontaktcontainer bzw. `provider_calendar_id`. Er
   *  gehoert zur Identitaet des Ziels — ein Termin ist nur zusammen mit
   *  seinem Kalender eindeutig adressierbar. */
  readonly container: string | null;
}

/**
 * Der Schreib-Port. Fünf Operationen, kein Calendar DELETE.
 *
 * Jede `bereiteVor…`-Methode mutiert nichts. `fuehreAus` mutiert genau die
 * eine übergebene, freigegebene Operation.
 */
export interface CoreWritePort {
  /** Eindeutiges Auflösen eines Kontakts. Mehrere Treffer sind ein Fehler,
   *  keine Auswahl. */
  findeKontakt(query: string): Promise<Zielobjekt>;
  /** Eindeutiges Auflösen eines Termins innerhalb eines Tages. */
  findeTermin(tag: string, query: string): Promise<Zielobjekt>;

  /** `zielName` benennt den Ablageort AUSDRUECKLICH. Auf diesem Mac gibt
   *  es mehrere Container bzw. Kalender; der Core waehlt nie selbst aus. */
  bereiteKontaktAnlegenVor(zielName: string,
                           name: string): Promise<VorbereiteteMutation>;
  bereiteKontaktAendernVor(ziel: Zielobjekt,
                           feld: string, wert: string): Promise<VorbereiteteMutation>;
  bereiteKontaktLoeschenVor(ziel: Zielobjekt): Promise<VorbereiteteMutation>;
  bereiteTerminAnlegenVor(zielName: string, titel: string, tag: string,
                          vonBis: string): Promise<VorbereiteteMutation>;
  bereiteTerminAendernVor(ziel: Zielobjekt,
                          neuerTitel: string): Promise<VorbereiteteMutation>;

  /** Freigeben UND ausführen — in dieser Reihenfolge, für genau diese
   *  vorbereitete Mutation. Der Aufrufer muss die Freigabe des Eigentümers
   *  bereits eingeholt haben; der Port erzwingt die Bindung an die
   *  `mutationId`. */
  fuehreAus(vorbereitet: VorbereiteteMutation): Promise<AusgefuehrteMutation>;
}

/** Die Fehlerklassen des Schreibwegs — jede endet fail-closed. */
export type SchreibFehlerArt =
  /** Der Server hat die Operation gar nicht erst freigeschaltet
   *  (Faehigkeitsvertrag). Kein Defekt der Eingabe — eine fehlende
   *  Freigabe des Kanals. */
  | 'operation_nicht_freigeschaltet'
  | 'quelle_nicht_erreichbar'
  | 'keine_berechtigung'
  | 'ziel_nicht_gefunden'
  | 'ziel_mehrdeutig'
  | 'ziel_veraendert'
  | 'container_nicht_verfuegbar'
  | 'freigabe_fehlt'
  | 'freigabe_gehoert_anderer_operation'
  | 'ausfuehrung_fehlgeschlagen'
  | 'readback_widerspricht';

export class SchreibFehler extends Error {
  readonly art: SchreibFehlerArt;
  /** PII-arme Zusatzangabe, etwa die Anzahl mehrdeutiger Treffer. */
  readonly detail?: string;
  /** In welchem Schritt es scheiterte. Entscheidend fuer die Ansage:
   *  „vorbereitet" heisst, dass NICHTS ausgefuehrt wurde — das darf der
   *  Text nicht verwischen (Livebefund 2026-08-11). */
  readonly phase: 'vorbereiten' | 'ausfuehren';
  /** Die typisierte Kennung des Servers, unveraendert durchgereicht. */
  readonly serverCode?: string;

  constructor(art: SchreibFehlerArt, detail?: string,
              phase: 'vorbereiten' | 'ausfuehren' = 'vorbereiten',
              serverCode?: string) {
    super(`write_failed:${art}`);
    this.name = 'SchreibFehler';
    this.art = art;
    this.detail = detail;
    this.phase = phase;
    this.serverCode = serverCode;
  }
}

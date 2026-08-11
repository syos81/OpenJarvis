// Jarvis Core v0 — der Lese-Port des Kerns.
//
// Dies ist die EINZIGE Schnittstelle, über die der Core an Kontakt- und
// Kalenderdaten kommt. Sie trägt ausschliesslich Leseoperationen: es gibt
// hier kein `prepare…`, kein `approve`, kein `execute`, kein Delete — und
// zwar nicht als Konvention, sondern typseitig. Was der Port nicht kennt,
// kann der Core nicht aufrufen.
//
// Die bestehenden Fachmodule bringen breitere Schnittstellen mit
// (`ContactsDataSource` enthält neben der Suche auch Mutationsschritte).
// Genau deshalb adaptiert `readAdapter.ts` am Rand auf diesen schmalen
// Port, statt die breite Schnittstelle in den Core zu reichen.

/** Ein Kontakttreffer — bewusst arm an personenbezogenen Feldern.
 *
 * Genug, um einen Treffer zu erkennen (Name, Organisation), plus reine
 * Zähler statt der Werte selbst. Der Core lädt und zeigt keine Adressen,
 * Telefonnummern oder Mailadressen. */
export interface KontaktTreffer {
  readonly id: string;
  readonly name: string;
  readonly organisation: string | null;
  readonly emailAnzahl: number;
  readonly telefonAnzahl: number;
}

/** Ein Termintreffer — die Felder, die einen Termin identifizierbar machen. */
export interface TerminTreffer {
  readonly id: string;
  readonly titel: string | null;
  readonly startUtc: string;
  readonly endeUtc: string;
  readonly ganztaegig: boolean;
  readonly kalender: string;
}

/** Was der Port über eine Suche sagt — inklusive der ehrlichen Aussage,
 *  dass mehr Treffer existieren als gezeigt werden. */
export interface KontaktErgebnis {
  readonly treffer: readonly KontaktTreffer[];
  /** Es gibt weitere Treffer jenseits des angeforderten Limits. */
  readonly weitereVorhanden: boolean;
}

/**
 * Der Lese-Port. Beide Methoden lesen — sie mutieren nichts und lösen
 * keinen Sync aus.
 *
 * Fehler werden NICHT verschluckt: eine nicht erreichbare Quelle wirft,
 * und die aufrufende Schicht macht daraus eine sichtbare Meldung. Ein
 * stiller Ersatzwert wäre ein falsches Grün.
 */
export interface CoreReadPort {
  /** Sucht im lokalen Kontaktbestand. `limit` begrenzt die Anzeige. */
  sucheKontakte(query: string, limit: number): Promise<KontaktErgebnis>;
  /** Liest Termine eines UTC-Fensters aus dem lokalen Bestand. */
  ladeTermine(startUtc: string, endeUtc: string): Promise<readonly TerminTreffer[]>;
}

/** Die eine Fehlerklasse des Ports: die lokale Quelle ist nicht erreichbar.
 *
 * Sie trennt „Backend weg" von „nichts gefunden". Nur so kann die Bar den
 * Unterschied sichtbar machen, statt Leere als Ergebnis auszugeben (ein
 * ausgefallener Lesepfad darf nie wie ein leeres Ergebnis aussehen). */
export class LeseQuelleNichtErreichbar extends Error {
  /** Die ursprüngliche Ursache — eigenes Feld statt `Error.cause`, das
   *  das Zielsprachniveau dieses Projekts nicht kennt. */
  readonly ursache?: unknown;

  constructor(readonly bereich: 'kontakte' | 'termine', ursache?: unknown) {
    super(`read_source_unavailable:${bereich}`);
    this.name = 'LeseQuelleNichtErreichbar';
    this.ursache = ursache;
  }
}

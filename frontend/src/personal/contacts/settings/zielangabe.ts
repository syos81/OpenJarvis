// Wie der Zielablageort auf der Freigabefläche steht.
//
// Reine Darstellung aus **gelieferten** Werten: Diese Datei berechnet keinen
// Namen, leitet keinen aus der Kennung ab und kennt keine Liste bekannter
// Konten. Sie entscheidet nur, wie das, was der Kern sagt, als Satz aussieht.
//
// Zwei Regeln, die aus dem Auftrag folgen:
//
//   * **Die Art trägt die Kategorie, die Anzahl den Zusammenhang.** Eine Null
//     macht aus einem synchronisierten Konto keinen lokalen Ablageort. Also
//     entsteht die Aussage „Konto" aus `container_type`, niemals aus der Zahl.
//   * **Ein fehlender Name wird nicht ersetzt.** `null` heisst „noch nicht
//     gelesen". Die Kennung darf danebenstehen — als Notbehelf, erkennbar als
//     solcher, nicht an der Stelle des Namens.

/** Der geschlossene Vorrat, wie ihn der Kern führt. */
export type Ablageart = 'local' | 'cardDAV' | 'exchange' | 'unassigned' | 'unknown';

export interface Zielangabe {
  /** Der Name, oder `null`, wenn er noch nicht gelesen wurde. */
  name: string | null;
  /** Ehrlicher Ersatztext, wenn der Name fehlt. Nie der Name selbst. */
  nameFehltHinweis: string | null;
  /** Die technische Kennung — steht zusätzlich, nie allein. */
  kennung: string | null;
  /** Ein Wort für die Art. Benennt die Art, behauptet keine Gefahr. */
  artText: string;
  /** Ob es ein synchronisiertes Konto ist. Folgt der Art, nie der Anzahl. */
  istKonto: boolean;
  /** Anzahl als Zusammenhang, oder `null`, wenn unbekannt. */
  anzahlText: string | null;
}

const ART_TEXT: Record<Ablageart, string> = {
  local: 'Lokal auf diesem Mac',
  cardDAV: 'Synchronisiertes Konto',
  exchange: 'Synchronisiertes Konto',
  unassigned: 'Ohne Ablageort',
  unknown: 'Art noch nicht gelesen',
};

/** Arten, die ein synchronisiertes Konto bezeichnen — aus dem Vorrat, nicht geraten. */
const KONTOARTEN: ReadonlySet<string> = new Set(['cardDAV', 'exchange']);

export function zielangabe(
  containerName: string | null,
  containerType: string,
  containerRef: string | null,
  anzahl: number | null,
): Zielangabe {
  const art = (containerType in ART_TEXT ? containerType : 'unknown') as Ablageart;
  return {
    name: containerName,
    nameFehltHinweis: containerName
      ? null
      : 'Name noch nicht gelesen — er steht nach dem nächsten Abgleich',
    kennung: containerRef,
    artText: ART_TEXT[art],
    // Die kategoriale Aussage haengt allein an der Art. Ein frisch angelegtes,
    // leeres Konto ist ein Konto.
    istKonto: KONTOARTEN.has(containerType),
    anzahlText:
      anzahl === null || anzahl === undefined
        ? null
        : `${anzahl} ${anzahl === 1 ? 'Kontakt' : 'Kontakte'}`,
  };
}

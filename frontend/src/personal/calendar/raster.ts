// Das Kalenderraster. PUR, client-sicher, ohne React.
//
// Übernommen aus dem alten Jarvis (`lib/contracts/calendar-grid.ts`,
// Baseline §3 A-1) und an zwei Stellen angepasst:
//
//  1. Die Zeitzone ist ein **Parameter**, keine Konstante. Vorher stand hier
//     fest `Europe/Berlin`; die Baseline verlangt die Systemzeitzone (B-7).
//  2. Die Jahresansicht ist neu (Paritätsvertrag P-2).
//
// Warum als eigener Vertrag und nicht in der Komponente:
//
// Ein Kalenderraster ist Rechnerei — Monatsanfang, Wochentagsversatz, Tage aus
// Vor- und Folgemonat, Zeitzone. Solche Logik in JSX zu verstecken hiesse, sie
// nur mit einem Browser prüfen zu können. Hier ist sie eine reine Funktion und
// damit beweisbar.
//
// Dies ist KEINE zweite Kalenderwahrheit: Es entstehen keine Termine und keine
// Zuordnungen. Es wird ausschliesslich gerechnet, WELCHE TAGE ein Raster zeigt
// — und daraus das Fenster abgeleitet, das der Sync laden soll.

export const RASTER_MODI = ['year', 'month', 'week', 'day'] as const;
export type RasterModus = (typeof RASTER_MODI)[number];

export const RASTER_LABELS: Readonly<Record<RasterModus, string>> = {
  year: 'Jahr', month: 'Monat', week: 'Woche', day: 'Tag',
};

/** Die Zeitzone der Anzeige. Vorgabe ist die des Systems — nie eine feste. */
export function systemZeitzone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Lokaler Kalendertag (YYYY-MM-DD) eines Instants. */
export function lokalerTag(iso: string, zone: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  // en-CA liefert stabil YYYY-MM-DD.
  return d.toLocaleDateString('en-CA', { timeZone: zone });
}

function key(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

/** Montag = 0 … Sonntag = 6. */
function isoWochentag(date: Date): number {
  return (date.getUTCDay() + 6) % 7;
}

/** Verschiebt einen Datumsschlüssel um n Tage (kalendarisch, driftfrei). */
export function plusTage(tag: string, n: number): string {
  const [y, m, d] = tag.split('-').map(Number);
  const next = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + n));
  return key(next.getUTCFullYear(), next.getUTCMonth(), next.getUTCDate());
}

/**
 * Der UTC-Instant, der 00:00 Ortszeit des gegebenen lokalen Kalendertags
 * entspricht. Ohne diese Umrechnung wäre das Fenster um den Zeitzonenversatz
 * verschoben — und ein Termin am Randtag fehlte.
 */
export function lokaleMitternachtUtc(tag: string, zone: string): string {
  const [y, m, d] = tag.split('-').map(Number);
  if (y === undefined || m === undefined || d === undefined) return '';
  // Versatz iterativ bestimmen: von der UTC-Annahme ausgehen und korrigieren.
  const guess = Date.UTC(y, m - 1, d, 0, 0, 0);
  const alsLokal = new Date(guess).toLocaleDateString('en-CA', { timeZone: zone });
  const teile = new Date(guess).toLocaleString('en-GB', {
    timeZone: zone, hour12: false, hour: '2-digit', minute: '2-digit',
  });
  const [hh, mm] = teile.split(':').map(Number);
  const tagesVersatz = alsLokal < tag ? -1 : alsLokal > tag ? 1 : 0;
  // Abstand der bei `guess` herrschenden Ortszeit zum Ziel (Ziel-Tag 00:00
  // lokal), in Minuten. Das Vorzeichen des Tagesversatzes gehört ADDIERT:
  // liegt die Ortszeit noch im Vortag, ist sie VOR dem Ziel.
  //
  // Der alte Jarvis subtrahierte hier — und lag damit bei jeder Zone WESTLICH
  // von UTC um zwei Tage daneben. Aufgefallen ist es nie, weil dort fest
  // `Europe/Berlin` stand (positiver Offset, Tagesversatz immer 0). Erst die
  // Parametrisierung der Zone (Baseline B-7) legt den Fehler frei; ein Test
  // hält ihn fest.
  const versatzMinuten = tagesVersatz * 24 * 60 + (hh ?? 0) * 60 + (mm ?? 0);
  return new Date(guess - versatzMinuten * 60_000).toISOString();
}

export interface RasterTag {
  readonly tag: string;
  /** Unterscheidet Tage der Periode von den Fülltagen ringsum. */
  readonly inPeriode: boolean;
}

export interface Raster {
  readonly modus: RasterModus;
  readonly tage: readonly RasterTag[];
  readonly titel: string;
  /** ISO-Instant des ersten Rastertags, 00:00 lokal (inklusiv). */
  readonly fensterStartUtc: string;
  /** ISO-Instant NACH dem letzten Rastertag, 00:00 lokal (exklusiv). */
  readonly fensterEndeUtc: string;
}

/**
 * Die lokalen Tage, an denen ein Termin im Raster erscheint.
 *
 * Hier lag im alten Jarvis ein realer Fehler — ein eintägiger Termin erschien
 * an ZWEI Tagen. Die Ursache ist eine Vermischung zweier Zeit-Konventionen,
 * und sie gilt unverändert:
 *
 *  · GANZTÄGIGE Termine sind bereits auf ihre lokalen Kalendertage normalisiert:
 *    der Datumsanteil IST der lokale Tag, verankert als UTC-Mitternacht, und
 *    das Ende ist EXKLUSIV. Sie müssen deshalb als Datums-STRINGS gelesen
 *    werden. Eine Zeitzonen-Umrechnung auf diese Mitternachts-Anker verschiebt
 *    das exklusive Ende in den Folgetag und zeichnet einen Tag zu viel.
 *
 *  · TERMINE MIT UHRZEIT sind rohe Instants und werden lokal aufgelöst, damit
 *    ein Abendtermin nicht in den UTC-Vortag rutscht. Das Ende ist ein
 *    Zeitpunkt, kein Tag: eine Sekunde zurück, damit ein Termin, der genau um
 *    Mitternacht endet, nicht schon den Folgetag markiert.
 */
export function termintage(
  termin: { readonly starts_at_utc: string; readonly ends_at_utc: string; readonly is_all_day: boolean },
  zone: string,
): string[] {
  const lauf = (start: string, letzter: string): string[] => {
    if (letzter <= start) return [start];
    const out: string[] = [];
    let cur = start;
    // Harte Grenze: ein Termin markiert nie mehr als ein Rasterfenster.
    for (let i = 0; i < 400 && cur <= letzter; i += 1) {
      out.push(cur);
      cur = plusTage(cur, 1);
    }
    return out;
  };

  if (termin.is_all_day) {
    // Datums-Strings, Ende EXKLUSIV: letzter Tag = Ende minus ein Tag.
    const start = termin.starts_at_utc.slice(0, 10);
    const endeExklusiv = termin.ends_at_utc.slice(0, 10);
    return lauf(start, endeExklusiv <= start ? start : plusTage(endeExklusiv, -1));
  }

  const start = lokalerTag(termin.starts_at_utc, zone);
  const letzter = lokalerTag(
    new Date(Date.parse(termin.ends_at_utc) - 1000).toISOString(), zone);
  return lauf(start, letzter);
}

const MONATSNAMEN = [
  'Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
  'Juli', 'August', 'September', 'Oktober', 'November', 'Dezember',
];

/**
 * Baut das sichtbare Raster für den gegebenen Anker-Tag.
 *
 * Monat: volle Wochen (Mo–So) inklusive angrenzender Tage — genau das, was der
 * Nutzer sieht, und damit genau der Zeitraum, den die Ansicht kennen muss.
 * Sonst blieben die Randtage leer und sähen aus wie frei.
 */
export function baueRaster(modus: RasterModus, anker: string, zone: string): Raster {
  const [y, m, d] = anker.split('-').map(Number);
  const jahr = y ?? 1970;
  const monat = (m ?? 1) - 1;
  const tag = d ?? 1;

  const tage: RasterTag[] = [];
  let titel: string;

  if (modus === 'day') {
    tage.push({ tag: anker, inPeriode: true });
    titel = new Date(Date.UTC(jahr, monat, tag)).toLocaleDateString('de-DE', {
      timeZone: 'UTC', weekday: 'long', day: '2-digit', month: 'long',
      year: 'numeric',
    });
  } else if (modus === 'week') {
    const ankerDatum = new Date(Date.UTC(jahr, monat, tag));
    const montag = new Date(ankerDatum.getTime() - isoWochentag(ankerDatum) * 86_400_000);
    for (let i = 0; i < 7; i += 1) {
      const cur = new Date(montag.getTime() + i * 86_400_000);
      tage.push({
        tag: key(cur.getUTCFullYear(), cur.getUTCMonth(), cur.getUTCDate()),
        inPeriode: true,
      });
    }
    const erster = tage[0]?.tag ?? anker;
    const letzter = tage[tage.length - 1]?.tag ?? anker;
    titel = `${erster.slice(8)}.–${letzter.slice(8)}. `
      + `${MONATSNAMEN[Number(letzter.slice(5, 7)) - 1]} ${letzter.slice(0, 4)}`;
  } else if (modus === 'year') {
    // Ganzes Jahr, Tag für Tag. Die Ansicht gruppiert selbst nach Monaten;
    // das Fenster ist dadurch exakt das Jahr — nicht mehr und nicht weniger.
    const start = new Date(Date.UTC(jahr, 0, 1));
    const ende = new Date(Date.UTC(jahr, 11, 31));
    const gesamt = Math.round((ende.getTime() - start.getTime()) / 86_400_000) + 1;
    for (let i = 0; i < gesamt; i += 1) {
      const cur = new Date(start.getTime() + i * 86_400_000);
      tage.push({
        tag: key(cur.getUTCFullYear(), cur.getUTCMonth(), cur.getUTCDate()),
        inPeriode: true,
      });
    }
    titel = String(jahr);
  } else {
    const ersterDesMonats = new Date(Date.UTC(jahr, monat, 1));
    const rasterStart = new Date(
      ersterDesMonats.getTime() - isoWochentag(ersterDesMonats) * 86_400_000);
    const letzterDesMonats = new Date(Date.UTC(jahr, monat + 1, 0));
    const rasterEnde = new Date(
      letzterDesMonats.getTime() + (6 - isoWochentag(letzterDesMonats)) * 86_400_000);
    const gesamt = Math.round(
      (rasterEnde.getTime() - rasterStart.getTime()) / 86_400_000) + 1;
    for (let i = 0; i < gesamt; i += 1) {
      const cur = new Date(rasterStart.getTime() + i * 86_400_000);
      tage.push({
        tag: key(cur.getUTCFullYear(), cur.getUTCMonth(), cur.getUTCDate()),
        inPeriode: cur.getUTCMonth() === monat,
      });
    }
    titel = `${MONATSNAMEN[monat]} ${jahr}`;
  }

  const ersterTag = tage[0]?.tag ?? anker;
  const letzterTag = tage[tage.length - 1]?.tag ?? anker;
  return {
    modus, tage, titel,
    fensterStartUtc: lokaleMitternachtUtc(ersterTag, zone),
    // Exklusiv: 00:00 des Tages NACH dem letzten Rastertag.
    fensterEndeUtc: lokaleMitternachtUtc(plusTage(letzterTag, 1), zone),
  };
}

/** Bewegt den Anker eine Periode vor/zurück. */
export function verschiebeAnker(modus: RasterModus, anker: string,
                                richtung: -1 | 1): string {
  if (modus === 'day') return plusTage(anker, richtung);
  if (modus === 'week') return plusTage(anker, richtung * 7);
  const [y, m] = anker.split('-').map(Number);
  if (modus === 'year') {
    return key((y ?? 1970) + richtung, 0, 1);
  }
  const next = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1 + richtung, 1));
  return key(next.getUTCFullYear(), next.getUTCMonth(), 1);
}

/** Der heutige lokale Tag. */
export function heute(zone: string): string {
  return lokalerTag(new Date().toISOString(), zone);
}

/**
 * Die Uhrzeit eines Termins in der Anzeigezone.
 *
 * Ganztägige und schwebende Termine haben keine Uhrzeit — sie bekommen hier
 * auch keine erfundene.
 */
export function uhrzeit(iso: string, zone: string): string {
  return new Date(iso).toLocaleTimeString('de-DE', {
    timeZone: zone, hour: '2-digit', minute: '2-digit',
  });
}

/** Anteil eines Tages (0…1), an dem ein Instant liegt — für die Zeitachse. */
export function tagesAnteil(iso: string, tag: string, zone: string): number {
  const tagStart = Date.parse(lokaleMitternachtUtc(tag, zone));
  const tagEnde = Date.parse(lokaleMitternachtUtc(plusTage(tag, 1), zone));
  const wert = Date.parse(iso);
  if (!Number.isFinite(tagStart) || !Number.isFinite(tagEnde)) return 0;
  return Math.min(1, Math.max(0, (wert - tagStart) / (tagEnde - tagStart)));
}

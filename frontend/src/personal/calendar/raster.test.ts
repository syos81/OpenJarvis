// Rasterlogik — die Prüfungen des alten Jarvis, mitgenommen und erweitert.
//
// Die Fälle stammen aus `lib/contracts/calendar-grid.test.ts`; zwei davon
// halten reale Fehler fest, die dort einmal aufgetreten sind (Termin an zwei
// Tagen, verschobener Fensterrand). Neu sind Jahresansicht und die
// Parametrisierung der Zeitzone.

import { describe, expect, it } from 'vitest';
import {
  RASTER_MODI,
  baueRaster,
  lokaleMitternachtUtc,
  lokalerTag,
  plusTage,
  systemWochenstart,
  systemZeitzone,
  tagesAnteil,
  termintage,
  verschiebeAnker,
  wochentagsKoepfe,
} from './raster';

const BERLIN = 'Europe/Berlin';
const NY = 'America/New_York';

describe('plusTage', () => {
  it('rechnet driftfrei über Monatsgrenzen', () => {
    expect(plusTage('2026-01-31', 1)).toBe('2026-02-01');
    expect(plusTage('2026-03-01', -1)).toBe('2026-02-28');
    expect(plusTage('2028-03-01', -1)).toBe('2028-02-29');
  });

  it('rechnet über Jahresgrenzen', () => {
    expect(plusTage('2026-12-31', 1)).toBe('2027-01-01');
    expect(plusTage('2026-01-01', -1)).toBe('2025-12-31');
  });

  it('überspringt keine Sommerzeitumstellung', () => {
    // Der Umstellungstag hat 23 Stunden — als Kalendertag zählt er trotzdem.
    expect(plusTage('2026-03-28', 1)).toBe('2026-03-29');
    expect(plusTage('2026-03-29', 1)).toBe('2026-03-30');
  });
});

describe('lokalerTag', () => {
  it('löst einen Abendtermin nicht in den UTC-Vortag auf', () => {
    // 23:30 Berlin am 10. ist 21:30 UTC am 10. — beide Male der 10.
    expect(lokalerTag('2026-08-10T21:30:00Z', BERLIN)).toBe('2026-08-10');
  });

  it('ordnet denselben Instant je Zone verschieden zu', () => {
    // 01:00 UTC am 11. ist in Berlin der 11., in New York noch der 10.
    expect(lokalerTag('2026-08-11T01:00:00Z', BERLIN)).toBe('2026-08-11');
    expect(lokalerTag('2026-08-11T01:00:00Z', NY)).toBe('2026-08-10');
  });

  it('liefert bei ungültiger Eingabe einen leeren Tag statt zu raten', () => {
    expect(lokalerTag('kein datum', BERLIN)).toBe('');
  });
});

describe('lokaleMitternachtUtc', () => {
  it('trifft Mitternacht in Sommer- und Winterzeit', () => {
    // Sommerzeit: 00:00 Berlin = 22:00 UTC des Vortags.
    expect(lokaleMitternachtUtc('2026-08-10', BERLIN)).toBe('2026-08-09T22:00:00.000Z');
    // Winterzeit: 00:00 Berlin = 23:00 UTC des Vortags.
    expect(lokaleMitternachtUtc('2026-01-10', BERLIN)).toBe('2026-01-09T23:00:00.000Z');
  });

  it('trifft Mitternacht in einer anderen Zone', () => {
    expect(lokaleMitternachtUtc('2026-08-10', NY)).toBe('2026-08-10T04:00:00.000Z');
  });

  it('trifft Mitternacht in UTC selbst', () => {
    expect(lokaleMitternachtUtc('2026-08-10', 'UTC')).toBe('2026-08-10T00:00:00.000Z');
  });
});

describe('baueRaster — Monat', () => {
  it('zeigt volle Wochen von Montag bis Sonntag', () => {
    const r = baueRaster('month', '2026-08-15', BERLIN);
    expect(r.tage.length % 7).toBe(0);
    expect(lokalerTag(r.fensterStartUtc, BERLIN)).toBe(r.tage[0]!.tag);
  });

  it('markiert Fülltage der Nachbarmonate als ausserhalb der Periode', () => {
    const r = baueRaster('month', '2026-08-15', BERLIN);
    // Der 1. August 2026 ist ein Samstag — davor liegen fünf Julitage.
    expect(r.tage[0]!.tag).toBe('2026-07-27');
    expect(r.tage[0]!.inPeriode).toBe(false);
    const august = r.tage.filter((t) => t.inPeriode);
    expect(august.length).toBe(31);
    expect(august[0]!.tag).toBe('2026-08-01');
  });

  it('trägt den Monatsnamen im Titel', () => {
    expect(baueRaster('month', '2026-08-15', BERLIN).titel).toBe('August 2026');
    expect(baueRaster('month', '2026-03-01', BERLIN).titel).toBe('März 2026');
  });

  it('schliesst das Fenster exklusiv nach dem letzten Rastertag', () => {
    const r = baueRaster('month', '2026-08-15', BERLIN);
    const letzter = r.tage[r.tage.length - 1]!.tag;
    expect(r.fensterEndeUtc).toBe(lokaleMitternachtUtc(plusTage(letzter, 1), BERLIN));
    expect(r.fensterEndeUtc > r.fensterStartUtc).toBe(true);
  });

  it('deckt einen Monat ab, der genau mit einer Woche beginnt', () => {
    // Der 1. Juni 2026 ist ein Montag: keine Fülltage davor.
    const r = baueRaster('month', '2026-06-10', BERLIN);
    expect(r.tage[0]!.tag).toBe('2026-06-01');
    expect(r.tage[0]!.inPeriode).toBe(true);
  });
});

describe('baueRaster — Woche', () => {
  it('beginnt immer am Montag', () => {
    for (const anker of ['2026-08-10', '2026-08-13', '2026-08-16']) {
      const r = baueRaster('week', anker, BERLIN);
      expect(r.tage.length).toBe(7);
      expect(r.tage[0]!.tag).toBe('2026-08-10');
    }
  });

  it('behandelt Sonntag als letzten Tag der Woche, nicht als ersten', () => {
    const r = baueRaster('week', '2026-08-16', BERLIN);
    expect(r.tage[6]!.tag).toBe('2026-08-16');
  });

  it('zählt alle Tage zur Periode', () => {
    expect(baueRaster('week', '2026-08-12', BERLIN).tage.every((t) => t.inPeriode))
      .toBe(true);
  });
});

describe('baueRaster — Tag', () => {
  it('enthält genau den Ankertag', () => {
    const r = baueRaster('day', '2026-08-12', BERLIN);
    expect(r.tage).toEqual([{ tag: '2026-08-12', inPeriode: true }]);
  });

  it('umfasst ein Fenster von genau 24 Stunden', () => {
    const r = baueRaster('day', '2026-08-12', BERLIN);
    const stunden = (Date.parse(r.fensterEndeUtc) - Date.parse(r.fensterStartUtc))
      / 3_600_000;
    expect(stunden).toBe(24);
  });

  it('umfasst am Umstellungstag 23 Stunden — und behauptet keine 24', () => {
    const r = baueRaster('day', '2026-03-29', BERLIN);
    const stunden = (Date.parse(r.fensterEndeUtc) - Date.parse(r.fensterStartUtc))
      / 3_600_000;
    expect(stunden).toBe(23);
  });
});

describe('baueRaster — Jahr', () => {
  it('enthält alle Tage des Jahres', () => {
    expect(baueRaster('year', '2026-05-05', BERLIN).tage.length).toBe(365);
    expect(baueRaster('year', '2028-05-05', BERLIN).tage.length).toBe(366);
  });

  it('beginnt am 1. Januar und endet am 31. Dezember', () => {
    const r = baueRaster('year', '2026-05-05', BERLIN);
    expect(r.tage[0]!.tag).toBe('2026-01-01');
    expect(r.tage[r.tage.length - 1]!.tag).toBe('2026-12-31');
    expect(r.titel).toBe('2026');
  });
});

describe('verschiebeAnker', () => {
  it('springt je Modus um genau eine Periode', () => {
    expect(verschiebeAnker('day', '2026-08-12', 1)).toBe('2026-08-13');
    expect(verschiebeAnker('week', '2026-08-12', 1)).toBe('2026-08-19');
    expect(verschiebeAnker('month', '2026-08-12', 1)).toBe('2026-09-01');
    expect(verschiebeAnker('year', '2026-08-12', 1)).toBe('2027-01-01');
  });

  it('springt rückwärts symmetrisch', () => {
    expect(verschiebeAnker('day', '2026-08-12', -1)).toBe('2026-08-11');
    expect(verschiebeAnker('week', '2026-08-12', -1)).toBe('2026-08-05');
    expect(verschiebeAnker('month', '2026-01-15', -1)).toBe('2025-12-01');
    expect(verschiebeAnker('year', '2026-08-12', -1)).toBe('2025-01-01');
  });

  it('bleibt beim Monatssprung im Monat, auch aus einem langen heraus', () => {
    // 31. Januar + 1 Monat darf nicht im März landen.
    expect(verschiebeAnker('month', '2026-01-31', 1)).toBe('2026-02-01');
  });

  it('deckt alle Modi ab', () => {
    for (const m of RASTER_MODI) {
      expect(typeof verschiebeAnker(m, '2026-08-12', 1)).toBe('string');
    }
  });
});

describe('termintage', () => {
  it('zeigt einen eintägigen Termin an GENAU EINEM Tag', () => {
    // Der Fehler, der im alten Jarvis real auftrat.
    expect(termintage({
      starts_at_utc: '2026-08-12T07:00:00Z',
      ends_at_utc: '2026-08-12T08:00:00Z',
      is_all_day: false,
    }, BERLIN)).toEqual(['2026-08-12']);
  });

  it('zeigt einen ganztägigen Termin an GENAU EINEM Tag', () => {
    // Realform (B2-Korrektur): lokale Mitternacht als Instant, Ende exklusiv.
    // 00:00 Berlin am 12. ist 22:00Z am 11.
    expect(termintage({
      starts_at_utc: '2026-08-11T22:00:00Z',
      ends_at_utc: '2026-08-12T22:00:00Z',
      is_all_day: true,
    }, BERLIN)).toEqual(['2026-08-12']);
  });

  it('spannt einen mehrtägigen ganztägigen Termin über alle Tage', () => {
    expect(termintage({
      starts_at_utc: '2026-08-11T22:00:00Z',
      ends_at_utc: '2026-08-14T22:00:00Z',
      is_all_day: true,
    }, BERLIN)).toEqual(['2026-08-12', '2026-08-13', '2026-08-14']);
  });

  it('markiert einen Termin, der genau um Mitternacht endet, nicht am Folgetag', () => {
    expect(termintage({
      starts_at_utc: '2026-08-12T20:00:00Z',   // 22:00 Berlin
      ends_at_utc: '2026-08-12T22:00:00Z',     // 00:00 Berlin am 13.
      is_all_day: false,
    }, BERLIN)).toEqual(['2026-08-12']);
  });

  it('spannt einen Termin über Mitternacht auf beide Tage', () => {
    expect(termintage({
      starts_at_utc: '2026-08-12T21:00:00Z',   // 23:00 Berlin
      ends_at_utc: '2026-08-12T23:00:00Z',     // 01:00 Berlin am 13.
      is_all_day: false,
    }, BERLIN)).toEqual(['2026-08-12', '2026-08-13']);
  });

  it('rechnet Uhrzeit-Termine je Zone unterschiedlich', () => {
    const mitUhrzeit = {
      starts_at_utc: '2026-08-11T01:00:00Z',
      ends_at_utc: '2026-08-11T02:00:00Z',
      is_all_day: false,
    };
    expect(termintage(mitUhrzeit, BERLIN)).toEqual(['2026-08-11']);
    expect(termintage(mitUhrzeit, NY)).toEqual(['2026-08-10']);
  });

  it('löst ganztägige Instants in der Anzeigezone auf (B2-Korrektur)', () => {
    // Der frühere Test behauptete Zonenunabhängigkeit — das setzte
    // normalisierte Datums-Anker voraus, die der reale Bestand nie hatte.
    // Ein Berliner Ganztagstermin liegt als Berliner Mitternachts-Instant
    // vor und löst sich in der Berliner Anzeige auf seinen Tag auf. Die
    // bewusste Grenze: eine ANDERE Anzeigezone verschiebt ihn — sie ist im
    // B2-Umfang identisch mit der Systemzone und im Handoff dokumentiert.
    const ganztags = {
      starts_at_utc: '2026-08-10T22:00:00Z',
      ends_at_utc: '2026-08-11T22:00:00Z',
      is_all_day: true,
    };
    expect(termintage(ganztags, BERLIN)).toEqual(['2026-08-11']);
  });

  it('behandelt ein Ende vor dem Beginn ohne Endlosschleife', () => {
    expect(termintage({
      starts_at_utc: '2026-08-12T00:00:00Z',
      ends_at_utc: '2026-08-10T00:00:00Z',
      is_all_day: true,
    }, BERLIN)).toEqual(['2026-08-12']);
  });
});

describe('tagesAnteil', () => {
  it('setzt Mitternacht auf 0 und den Tagesabschluss auf 1', () => {
    expect(tagesAnteil(lokaleMitternachtUtc('2026-08-12', BERLIN),
                       '2026-08-12', BERLIN)).toBe(0);
    expect(tagesAnteil(lokaleMitternachtUtc('2026-08-13', BERLIN),
                       '2026-08-12', BERLIN)).toBe(1);
  });

  it('setzt Mittag auf die Tagesmitte', () => {
    // 12:00 Berlin = 10:00 UTC im Sommer.
    expect(tagesAnteil('2026-08-12T10:00:00Z', '2026-08-12', BERLIN)).toBeCloseTo(0.5);
  });

  it('klemmt Werte ausserhalb des Tages', () => {
    expect(tagesAnteil('2020-01-01T00:00:00Z', '2026-08-12', BERLIN)).toBe(0);
    expect(tagesAnteil('2030-01-01T00:00:00Z', '2026-08-12', BERLIN)).toBe(1);
  });
});

describe('systemZeitzone', () => {
  it('liefert eine nichtleere Zone und niemals eine fest verdrahtete', () => {
    const zone = systemZeitzone();
    expect(zone.length).toBeGreaterThan(0);
    // Der Punkt der Baseline B-7: die Zone kommt vom System, nicht aus dem Code.
    expect(lokaleMitternachtUtc('2026-08-12', zone)).not.toBe('');
  });
});

describe('Wochenbeginn ist Konfiguration, nie Konstante (B2)', () => {
  it('verschiebt das Monatsraster bei Wochenbeginn Sonntag korrekt', () => {
    // August 2026 beginnt an einem Samstag. Bei Wochenbeginn Sonntag (Versatz
    // 6) beginnt das Raster am Sonntag, 26. Juli; bei Montag am 27. Juli.
    const sonntag = baueRaster('month', '2026-08-15', BERLIN, 6);
    const montag = baueRaster('month', '2026-08-15', BERLIN, 0);
    expect(sonntag.tage[0]!.tag).toBe('2026-07-26');
    expect(montag.tage[0]!.tag).toBe('2026-07-27');
    expect(sonntag.tage.length % 7).toBe(0);
    expect(montag.tage.length % 7).toBe(0);
    // Der letzte Rastertag schliesst die Woche in derselben Ordnung.
    const letzterSonntag = sonntag.tage[sonntag.tage.length - 1]!.tag;
    const letzterMontag = montag.tage[montag.tage.length - 1]!.tag;
    expect(new Date(`${letzterSonntag}T00:00:00Z`).getUTCDay()).toBe(6);
    expect(new Date(`${letzterMontag}T00:00:00Z`).getUTCDay()).toBe(0);
  });

  it('verschiebt die Wochenansicht mit dem Wochenbeginn', () => {
    const sonntag = baueRaster('week', '2026-08-12', BERLIN, 6);
    const montag = baueRaster('week', '2026-08-12', BERLIN, 0);
    expect(sonntag.tage[0]!.tag).toBe('2026-08-09');
    expect(montag.tage[0]!.tag).toBe('2026-08-10');
  });

  it('ordnet die Wochentagskoepfe in derselben Ordnung wie das Raster', () => {
    const sonntag = wochentagsKoepfe(6, 'de-DE');
    const montag = wochentagsKoepfe(0, 'de-DE');
    expect(sonntag[0]!.toLowerCase().startsWith('so')).toBe(true);
    expect(montag[0]!.toLowerCase().startsWith('mo')).toBe(true);
    expect(sonntag.length).toBe(7);
    // Locale-uebliche Schreibweise, keine Vollgrossschreibung.
    for (const kopf of montag) expect(kopf).toMatch(/[a-zäöü]/);
  });

  it('leitet den Systemwochenbeginn aus der Locale-Schicht ab', () => {
    // de-DE: CLDR-Vorgabe Montag; en-US: Sonntag. Beide über dieselbe Quelle.
    expect(systemWochenstart('de-DE')).toBe(0);
    expect(systemWochenstart('en-US')).toBe(6);
  });
});

describe('Ganztagstermine sind Instants, keine Datums-Strings (B2-Korrektur)', () => {
  // Mechanisch belegt an der produktiven Datenbank (2026-08-09): EventKit
  // liefert und der Sync speichert ganztaegige Termine als ROHE INSTANTS der
  // lokalen Mitternacht (Berlin: …T22:00:00Z), nicht als normalisierte
  // UTC-Mitternachts-Anker. Der alte String-Schnitt [:10] verschob deshalb
  // JEDEN deutschen Ganztagstermin einen Tag zurueck — im Livevergleich mit
  // Apple Kalender als globale Ein-Tages-Verschiebung sichtbar.
  it('ordnet einen ganztaegigen Berliner Termin dem richtigen lokalen Tag zu', () => {
    expect(termintage({
      starts_at_utc: '2026-08-27T22:00:00Z',   // 00:00 Berlin am 28.
      ends_at_utc: '2026-08-28T22:00:00Z',     // exklusiv: 00:00 am 29.
      is_all_day: true,
    }, BERLIN)).toEqual(['2026-08-28']);
  });

  it('spannt einen mehrtaegigen Ganztagstermin ueber genau seine Tage', () => {
    // Gegentest zum alten Verdacht „ein Tag zu viel": das exklusive Ende
    // minus eine Sekunde liegt im letzten enthaltenen Tag, nie im Folgetag.
    expect(termintage({
      starts_at_utc: '2026-08-27T22:00:00Z',
      ends_at_utc: '2026-08-30T22:00:00Z',
      is_all_day: true,
    }, BERLIN)).toEqual(['2026-08-28', '2026-08-29', '2026-08-30']);
  });

  it('ordnet westliche Zonen genauso korrekt zu', () => {
    // New York: 00:00 lokal am 28. ist 04:00Z desselben Tages.
    expect(termintage({
      starts_at_utc: '2026-08-28T04:00:00Z',
      ends_at_utc: '2026-08-29T04:00:00Z',
      is_all_day: true,
    }, 'America/New_York')).toEqual(['2026-08-28']);
  });
});

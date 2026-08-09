// Die Flächen der Kalenderoberfläche: Seitenleiste, Raster, Detail.
//
// Reine Präsentation — kein Laden, kein Zustand über die Auswahl hinaus, kein
// Provideraufruf. Die eine Ehrlichkeitsregel dieser Datei:
//
//   Ein Tag ohne Termine IM geladenen Fenster ist FREI.
//   Ein Tag AUSSERHALB des geladenen Fensters ist UNBEKANNT.
//
// Diese beiden dürfen nie gleich aussehen — sonst behauptet ein hübsches
// Raster Wissen, das es nicht hat.

import type { KalenderZeile, Termin } from './api';
import {
  type Raster, baueRaster, lokalerTag, plusTage, tagesAnteil, termintage,
  uhrzeit, wochentagsKoepfe, wochentagsLabel,
} from './raster';

const MONATSKUERZEL = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];

export function farbeVon(t: { calendar_color: string | null }): string {
  return t.calendar_color ?? 'var(--pjk-color-fallback)';
}

/** Lesbare Textfarbe auf farbigem Grund — reine Kontrastwahl, keine Fachlogik. */
export function lesbarAuf(farbe: string): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(farbe);
  if (m === null) return 'var(--pjk-ink)';
  const n = parseInt(m[1]!, 16);
  const lum = (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255)
    + 0.114 * (n & 255)) / 255;
  return lum > 0.6 ? '#1a1a1a' : '#f5f4ef';
}

function mitAlpha(farbe: string, alpha: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(farbe);
  if (m === null) return farbe;
  const n = parseInt(m[1]!, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// ── Seitenleiste ────────────────────────────────────────────────────────────

export interface SidebarProps {
  kalender: KalenderZeile[];
  versteckt: ReadonlySet<string>;
  aufAendern: (id: string) => void;
  zone: string;
  /** Miniaturmonat unten in der Seitenleiste (B2, wie die Referenz). */
  anker: string;
  heuteTag: string;
  wochenstart: number;
  aufTag: (tag: string) => void;
}

/** Der kleine Monat unten in der Seitenleiste — reine Navigation, kein Laden. */
export function MiniMonat({ anker, heuteTag, wochenstart, zone, aufTag }: {
  anker: string; heuteTag: string; wochenstart: number; zone: string;
  aufTag: (tag: string) => void;
}) {
  const raster = baueRaster('month', anker, zone, wochenstart);
  const koepfe = wochentagsKoepfe(wochenstart);
  return (
    <div data-testid="kalender-minimonat" className="px-3 pt-2 pb-3"
      style={{ borderTop: '1px solid var(--pjk-line-soft)' }}>
      <p className="text-[11px] font-semibold mb-1" style={{ color: 'var(--pjk-ink)' }}>
        {raster.titel}
      </p>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(7, 1fr)' }}>
        {koepfe.map((w, i) => (
          <div key={`${w}-${i}`} className="text-[9px] text-center"
            style={{ color: 'var(--pjk-ink-dim)' }}>{w[0]}</div>
        ))}
        {raster.tage.map((d) => {
          const istHeute = d.tag === heuteTag;
          return (
            <button key={d.tag} type="button" data-date={d.tag}
              onClick={() => aufTag(d.tag)}
              className="text-[10px] tabular-nums"
              style={{
                height: 'var(--pjk-year-cell)',
                borderRadius: '50%',
                color: istHeute ? '#fff' : 'var(--pjk-ink)',
                background: istHeute ? 'var(--pjk-heute)' : 'transparent',
                opacity: d.inPeriode ? 1 : 'var(--pjk-outside-opacity)',
              }}>
              {Number(d.tag.slice(8))}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Kalender nach Quelle gruppiert — wie Apple (P-1). */
export function CalendarSidebar({ kalender, versteckt, aufAendern, zone,
                                  anker, heuteTag, wochenstart, aufTag }: SidebarProps) {
  const gruppen = new Map<string, KalenderZeile[]>();
  for (const k of kalender) {
    const name = k.source_title ?? 'Andere';
    const liste = gruppen.get(name);
    if (liste) liste.push(k);
    else gruppen.set(name, [k]);
  }

  return (
    <nav aria-label="Kalender" className="h-full flex flex-col py-2"
      style={{ borderRight: '1px solid var(--pjk-line)',
               background: 'var(--pjk-surface-2)' }}>
      <div className="flex-1 overflow-y-auto">
      {kalender.length === 0 && (
        <p className="px-3 py-2 text-xs" style={{ color: 'var(--pjk-ink-dim)' }}>
          Noch kein Kalender bekannt — synchronisieren liest sie ein.
        </p>
      )}
      {[...gruppen.entries()].map(([quelle, liste]) => (
        <section key={quelle} className="mb-3">
          <h3 className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: 'var(--pjk-ink-dim)' }}>{quelle}</h3>
          <ul>
            {liste.map((k) => {
              const aus = versteckt.has(k.id);
              return (
                <li key={k.id}>
                  <label className="flex items-center gap-2 px-3 py-1 cursor-pointer text-xs">
                    <input
                      type="checkbox"
                      checked={!aus}
                      onChange={() => aufAendern(k.id)}
                      aria-label={`${k.display_name} ${aus ? 'einblenden' : 'ausblenden'}`}
                    />
                    <span aria-hidden style={{
                      width: 'var(--pjk-dot-size)', height: 'var(--pjk-dot-size)',
                      borderRadius: 2, flexShrink: 0,
                      background: aus ? 'transparent' : (k.color ?? 'var(--pjk-color-fallback)'),
                      border: `1px solid ${k.color ?? 'var(--pjk-color-fallback)'}`,
                    }} />
                    <span className="truncate"
                      style={{ color: aus ? 'var(--pjk-ink-dim)' : 'var(--pjk-ink)' }}>
                      {k.display_name}
                    </span>
                    {/* Provider-Wahrheit sichtbar machen: ein nicht schreibbarer
                        Kalender sagt das hier, nicht erst beim Speichern (P-6). */}
                    {!k.is_writable && (
                      <span title="Nur lesbar" aria-label="Nur lesbar"
                        className="text-[9px] flex-shrink-0"
                        style={{ color: 'var(--pjk-ink-dim)' }}>🔒</span>
                    )}
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      </div>
      {/* B2: Miniaturmonat unten, wie die Referenz. Der frühere Erklärtext
          ist entfallen — das Ein-/Ausblenden bleibt trotzdem reine Ansicht. */}
      <MiniMonat anker={anker} heuteTag={heuteTag} wochenstart={wochenstart}
        zone={zone} aufTag={aufTag} />
    </nav>
  );
}

// ── Gemeinsames ─────────────────────────────────────────────────────────────

export interface RasterProps {
  raster: Raster;
  termineProTag: Map<string, Termin[]>;
  zone: string;
  heuteTag: string;
  /** Der Bereich, über den der gespeicherte Bestand überhaupt etwas weiss. */
  bekanntVon: string | null;
  bekanntBis: string | null;
  aufAuswahl: (t: Termin) => void;
  ausgewaehlt: string | null;
  /** B2: erster Wochentag als ISO-Versatz (0 = Montag … 6 = Sonntag). */
  wochenstart: number;
  /** B2: lesende Tagesauswahl per Klick. */
  gewaehlterTag: string | null;
  aufTagAuswahl: (tag: string) => void;
}

/** Ob über diesen Tag überhaupt etwas bekannt ist. */
function istBekannt(tag: string, von: string | null, bis: string | null,
                    zone: string): boolean {
  if (von === null || bis === null) return false;
  return tag >= lokalerTag(von, zone) && tag < lokalerTag(bis, zone);
}

function TerminChip({ t, tag, zone, aufAuswahl, ausgewaehlt }: {
  t: Termin; tag: string; zone: string;
  aufAuswahl: (t: Termin) => void; ausgewaehlt: string | null;
}) {
  const farbe = farbeVon(t);
  const aktiv = ausgewaehlt === t.id;
  const serie = t.recurrence_rule !== null;
  // B2, wie die Referenz: ein zeitgebundener Termin ist Punkt + Titel +
  // rechtsbuendige Uhrzeit — KEIN gefuellter Block nur wegen einer Uhrzeit.
  // Ganztaegige Termine bleiben der gefuellte Balken.
  return (
    <button
      type="button"
      data-testid="kalender-termin"
      data-event-id={t.id}
      onClick={(e) => { e.stopPropagation(); aufAuswahl(t); }}
      aria-current={aktiv ? 'true' : undefined}
      title={`${t.title ?? 'Ohne Titel'} — ${t.calendar_name}`}
      className="flex w-full items-center gap-1 px-1 text-left truncate"
      style={{
        minHeight: 'var(--pjk-chip-height)',
        borderRadius: 'var(--pjk-chip-radius)',
        background: t.is_all_day ? farbe : 'transparent',
        outline: aktiv ? '2px solid var(--pjk-auswahl)' : 'none',
      }}
    >
      {!t.is_all_day && (
        <span aria-hidden className="flex-shrink-0" style={{
          width: 6, height: 6, borderRadius: '50%', background: farbe }} />
      )}
      {/* Serien werden als Serien gezeigt, bevor jemand etwas anfasst (P-8). */}
      {serie && <span aria-label="Serie" title="Serie"
        className="text-[9px] flex-shrink-0">↻</span>}
      <span className="text-[11px] truncate flex-1 min-w-0" style={{
        color: t.is_all_day ? lesbarAuf(farbe) : 'var(--pjk-ink)',
        fontWeight: t.is_all_day ? 600 : 500,
      }}>
        {t.title ?? 'Ohne Titel'}
      </span>
      {!t.is_all_day && (
        <span className="text-[10px] flex-shrink-0 tabular-nums text-right"
          style={{ color: 'var(--pjk-ink-dim)' }}>
          {uhrzeit(t.starts_at_utc, zone)}
        </span>
      )}
    </button>
  );
}

// ── Monat ───────────────────────────────────────────────────────────────────

export function MonatsRaster(p: RasterProps) {
  const { raster, termineProTag, zone, heuteTag, aufAuswahl, ausgewaehlt,
          wochenstart, gewaehlterTag, aufTagAuswahl } = p;
  const koepfe = wochentagsKoepfe(wochenstart);
  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="grid flex-shrink-0"
        style={{ gridTemplateColumns: 'repeat(7, minmax(0, 1fr))' }}>
        {koepfe.map((w, i) => (
          <div key={`${w}-${i}`} role="columnheader"
            className="text-[11px] font-medium text-right pr-2"
            style={{
              height: 'var(--pjk-weekday-height)',
              color: 'var(--pjk-ink-dim)',
              borderBottom: '1px solid var(--pjk-line)',
            }}>{w}</div>
        ))}
      </div>
      <div role="grid" aria-label={raster.titel}
        className="grid flex-1 min-h-0 overflow-y-auto"
        style={{
          gridTemplateColumns: 'repeat(7, minmax(0, 1fr))',
          gridAutoRows: 'minmax(var(--pjk-month-cell-min), auto)',
        }}>
        {raster.tage.map((d, i) => {
          const termine = termineProTag.get(d.tag) ?? [];
          const istHeute = d.tag === heuteTag;
          const istGewaehlt = d.tag === gewaehlterTag;
          const bekannt = istBekannt(d.tag, p.bekanntVon, p.bekanntBis, zone);
          return (
            <div key={d.tag} role="gridcell" data-testid="kalender-tag"
              data-date={d.tag} data-bekannt={bekannt ? '1' : '0'}
              data-selected={istGewaehlt ? '1' : '0'}
              aria-selected={istGewaehlt}
              onClick={() => aufTagAuswahl(d.tag)}
              className={`p-1 min-w-0 cursor-default ${bekannt ? '' : 'pjk-unbekannt'}`}
              style={{
                // B2-Livebefund: klar sichtbare Zellgrenzen wie die Referenz.
                borderRight: (i + 1) % 7 === 0 ? 'none' : '1px solid var(--pjk-line)',
                borderBottom: '1px solid var(--pjk-line)',
                opacity: d.inPeriode ? 1 : 'var(--pjk-outside-opacity)',
              }}>
              {/* B2, wie die Referenz: Tageszahl oben RECHTS; heute als roter
                  gefuellter Kreis; der gewaehlte Tag als grauer Kreis. */}
              <div className="flex items-center justify-end mb-0.5">
                <span className="inline-flex items-center justify-center text-[11px] font-medium tabular-nums"
                  style={{
                    minWidth: 'var(--pjk-daynumber-size)',
                    height: 'var(--pjk-daynumber-size)',
                    borderRadius: '50%',
                    color: istHeute || istGewaehlt ? '#fff' : 'var(--pjk-ink)',
                    background: istHeute ? 'var(--pjk-heute)'
                      : istGewaehlt ? 'var(--pjk-auswahl)' : 'transparent',
                    outline: istHeute && istGewaehlt
                      ? '2px solid var(--pjk-auswahl)' : 'none',
                  }}>
                  {Number(d.tag.slice(8))}
                </span>
              </div>
              <div className="flex flex-col" style={{ gap: 'var(--pjk-chip-gap)' }}>
                {termine.map((t) => (
                  <TerminChip key={`${t.id}-${d.tag}`} t={t} tag={d.tag} zone={zone}
                    aufAuswahl={aufAuswahl} ausgewaehlt={ausgewaehlt} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Woche und Tag: echte Zeitachse ──────────────────────────────────────────

export function ZeitRaster(p: RasterProps) {
  const { raster, termineProTag, zone, heuteTag, aufAuswahl, ausgewaehlt } = p;
  const spalten = raster.tage.length;
  const stunden = Array.from({ length: 24 }, (_, i) => i);

  const ganztags = new Map<string, Termin[]>();
  const mitUhrzeit = new Map<string, Termin[]>();
  for (const d of raster.tage) {
    const alle = termineProTag.get(d.tag) ?? [];
    ganztags.set(d.tag, alle.filter((t) => t.is_all_day));
    mitUhrzeit.set(d.tag, alle.filter((t) => !t.is_all_day));
  }
  const maxGanztags = Math.max(0, ...[...ganztags.values()].map((l) => l.length));

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Kopf mit Wochentagen */}
      <div className="flex flex-shrink-0" style={{ borderBottom: '1px solid var(--pjk-line)' }}>
        <div style={{ width: 'var(--pjk-gutter-width)', flexShrink: 0 }} />
        {raster.tage.map((d) => {
          const istHeute = d.tag === heuteTag;
          return (
            <div key={d.tag} className="flex-1 min-w-0 text-center py-1">
              <div className="text-[10px]" style={{ color: 'var(--pjk-ink-dim)' }}>
                {wochentagsLabel(d.tag)}
              </div>
              <div className="inline-flex items-center justify-center text-[12px] font-medium tabular-nums"
                style={{
                  minWidth: 'var(--pjk-daynumber-size)',
                  height: 'var(--pjk-daynumber-size)',
                  borderRadius: '50%',
                  color: istHeute ? '#fff' : 'var(--pjk-ink)',
                  background: istHeute ? 'var(--pjk-heute)' : 'transparent',
                }}>
                {Number(d.tag.slice(8))}
              </div>
            </div>
          );
        })}
      </div>

      {/* Ganztagsbereich — eine eigene Art von Termin, kein besonders langer. */}
      <div className="flex flex-shrink-0"
        style={{
          borderBottom: '1px solid var(--pjk-line)',
          minHeight: maxGanztags > 0 ? 'var(--pjk-allday-min-height)' : 0,
        }}>
        <div className="text-[9px] text-right pr-1 pt-1"
          style={{ width: 'var(--pjk-gutter-width)', flexShrink: 0,
                   color: 'var(--pjk-ink-dim)' }}>
          {maxGanztags > 0 ? 'ganztägig' : ''}
        </div>
        {raster.tage.map((d) => (
          <div key={d.tag} data-testid="kalender-ganztags" data-date={d.tag}
            className="flex-1 min-w-0 p-0.5 flex flex-col"
            style={{ gap: 'var(--pjk-chip-gap)',
                     borderLeft: '1px solid var(--pjk-line-soft)' }}>
            {(ganztags.get(d.tag) ?? []).map((t) => (
              <TerminChip key={`${t.id}-${d.tag}`} t={t} tag={d.tag} zone={zone}
                aufAuswahl={aufAuswahl} ausgewaehlt={ausgewaehlt} />
            ))}
          </div>
        ))}
      </div>

      {/* Zeitachse */}
      <div className="flex flex-1 min-h-0 overflow-y-auto">
        <div style={{ width: 'var(--pjk-gutter-width)', flexShrink: 0 }}>
          {stunden.map((h) => (
            <div key={h} className="text-[9px] text-right pr-1 tabular-nums"
              style={{ height: 'var(--pjk-hour-height)', color: 'var(--pjk-ink-dim)' }}>
              {String(h).padStart(2, '0')}:00
            </div>
          ))}
        </div>
        {raster.tage.map((d) => {
          const bekannt = istBekannt(d.tag, p.bekanntVon, p.bekanntBis, zone);
          return (
            <div key={d.tag} data-testid="kalender-tagesspalte" data-date={d.tag}
              data-bekannt={bekannt ? '1' : '0'}
              className={`flex-1 min-w-0 relative ${bekannt ? '' : 'pjk-unbekannt'}`}
              style={{ borderLeft: '1px solid var(--pjk-line-soft)',
                       height: `calc(24 * var(--pjk-hour-height))` }}>
              {stunden.map((h) => (
                <div key={h} style={{
                  position: 'absolute', left: 0, right: 0,
                  top: `calc(${h} * var(--pjk-hour-height))`,
                  borderTop: '1px solid var(--pjk-line-soft)',
                }} />
              ))}
              {(mitUhrzeit.get(d.tag) ?? []).map((t) => {
                // Anteil des Tages statt Stundenrechnung: das ist auch am
                // Umstellungstag richtig, an dem der Tag 23 oder 25 Stunden hat.
                const von = tagesAnteil(t.starts_at_utc, d.tag, zone);
                const bis = tagesAnteil(t.ends_at_utc, d.tag, zone);
                const hoehe = Math.max(bis - von, 0.012);
                const farbe = farbeVon(t);
                const aktiv = ausgewaehlt === t.id;
                return (
                  <button key={`${t.id}-${d.tag}`} type="button"
                    data-testid="kalender-termin" data-event-id={t.id}
                    onClick={() => aufAuswahl(t)}
                    title={`${t.title ?? 'Ohne Titel'} — ${t.calendar_name}`}
                    className="absolute left-0.5 right-0.5 text-left px-1 overflow-hidden"
                    style={{
                      top: `${von * 100}%`, height: `${hoehe * 100}%`,
                      borderRadius: 'var(--pjk-chip-radius)',
                      background: mitAlpha(farbe, 0.2),
                      borderLeft: `3px solid ${farbe}`,
                      outline: aktiv ? '2px solid var(--pjk-heute)' : 'none',
                    }}>
                    <span className="text-[10px] block truncate"
                      style={{ color: 'var(--pjk-ink)' }}>
                      {uhrzeit(t.starts_at_utc, zone)} {t.title ?? 'Ohne Titel'}
                    </span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Jahr ────────────────────────────────────────────────────────────────────

export function JahresRaster(p: RasterProps & { aufTag: (tag: string) => void }) {
  const { raster, termineProTag, heuteTag, aufTag, wochenstart } = p;
  const jahr = raster.tage[0]?.tag.slice(0, 4) ?? '';
  const monate = Array.from({ length: 12 }, (_, m) => m);
  const koepfe = wochentagsKoepfe(wochenstart);

  return (
    <div className="grid gap-4 p-3 overflow-y-auto h-full"
      style={{ gridTemplateColumns:
        'repeat(auto-fill, minmax(var(--pjk-year-month-min), 1fr))' }}>
      {monate.map((m) => {
        const praefix = `${jahr}-${String(m + 1).padStart(2, '0')}`;
        const tage = raster.tage.filter((d) => d.tag.startsWith(praefix));
        const ersterWochentag = tage.length > 0
          ? ((new Date(`${tage[0]!.tag}T00:00:00Z`).getUTCDay() + 6) % 7
             - wochenstart + 7) % 7 : 0;
        return (
          <section key={m} aria-label={`${MONATSKUERZEL[m]} ${jahr}`}>
            <h3 className="text-[12px] font-semibold mb-1"
              style={{ color: 'var(--pjk-heute)' }}>{MONATSKUERZEL[m]}</h3>
            <div className="grid" style={{ gridTemplateColumns: 'repeat(7, 1fr)' }}>
              {koepfe.map((w, i) => (
                <div key={`${w}-${i}`} className="text-[9px] text-center"
                  style={{ color: 'var(--pjk-ink-dim)' }}>{w[0]}</div>
              ))}
              {Array.from({ length: ersterWochentag }, (_, i) => (
                <div key={`leer-${i}`} />
              ))}
              {tage.map((d) => {
                const anzahl = (termineProTag.get(d.tag) ?? []).length;
                const istHeute = d.tag === heuteTag;
                return (
                  <button key={d.tag} type="button" data-testid="kalender-jahrestag"
                    data-date={d.tag} onClick={() => aufTag(d.tag)}
                    title={anzahl > 0 ? `${anzahl} Termin(e)` : undefined}
                    className="text-[10px] tabular-nums relative"
                    style={{
                      height: 'var(--pjk-year-cell)',
                      color: istHeute ? '#fff' : 'var(--pjk-ink)',
                      background: istHeute ? 'var(--pjk-heute)' : 'transparent',
                      borderRadius: '50%',
                      fontWeight: anzahl > 0 ? 700 : 400,
                    }}>
                    {Number(d.tag.slice(8))}
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

// ── Detail ──────────────────────────────────────────────────────────────────

function zeitBeschreibung(t: Termin, zone: string): string {
  if (t.is_all_day) {
    // Instants, kein String-Schnitt — dieselbe B2-Korrektur wie in
    // `termintage`: die lokale Mitternacht liegt als roher Instant vor.
    const tage = termintage(t, zone);
    const start = tage[0] ?? lokalerTag(t.starts_at_utc, zone);
    const letzter = tage[tage.length - 1] ?? start;
    return start === letzter ? `Ganztägig · ${start}`
                             : `Ganztägig · ${start} bis ${letzter}`;
  }
  return `${uhrzeit(t.starts_at_utc, zone)} – ${uhrzeit(t.ends_at_utc, zone)}`;
}

export function TerminDetail({ termin, zone }: { termin: Termin | null; zone: string }) {
  if (termin === null) {
    return (
      <aside className="h-full p-4 text-xs" style={{
        borderLeft: '1px solid var(--pjk-line)', color: 'var(--pjk-ink-dim)' }}>
        Keinen Termin ausgewählt.
      </aside>
    );
  }
  const farbe = farbeVon(termin);
  return (
    <aside aria-label="Termindetails" className="h-full overflow-y-auto p-4"
      style={{ borderLeft: '1px solid var(--pjk-line)' }}>
      <div className="flex items-start gap-2 mb-3">
        <span aria-hidden style={{
          width: 'var(--pjk-dot-size)', height: 'var(--pjk-dot-size)',
          borderRadius: 2, background: farbe, marginTop: 5, flexShrink: 0 }} />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold break-words"
            style={{ color: 'var(--pjk-ink)' }}>
            {termin.title ?? 'Ohne Titel'}
          </h2>
          <p className="text-[11px]" style={{ color: 'var(--pjk-ink-dim)' }}>
            {termin.calendar_name}
          </p>
        </div>
      </div>

      <dl className="text-[11px] space-y-2" style={{ color: 'var(--pjk-ink)' }}>
        <div>
          <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Zeit</dt>
          <dd>{zeitBeschreibung(termin, zone)}</dd>
          {/* Eine abweichende Zeitzone gehoert sichtbar gemacht; eine fehlende
              wird ehrlich als schwebend benannt statt stillschweigend auf die
              Anzeigezone gesetzt (P-10). */}
          <dd style={{ color: 'var(--pjk-ink-dim)' }}>
            {termin.time_zone === null
              ? (termin.is_all_day ? 'ohne Zeitzone (ganztägig)' : 'schwebend — ohne feste Zeitzone')
              : termin.time_zone !== zone
                ? `Zeitzone des Termins: ${termin.time_zone} · angezeigt in ${zone}`
                : `Zeitzone: ${termin.time_zone}`}
          </dd>
        </div>

        {termin.recurrence_rule !== null && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Serie</dt>
            <dd>
              {String(termin.recurrence_rule.frequency ?? 'wiederkehrend')}
              {typeof termin.recurrence_rule.interval === 'number'
                && termin.recurrence_rule.interval > 1
                ? `, alle ${termin.recurrence_rule.interval}` : ''}
              {termin.is_detached ? ' · abgelöste Einzelinstanz' : ''}
            </dd>
          </div>
        )}

        {termin.location !== null && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Ort</dt>
            <dd className="break-words">{termin.location}</dd>
          </div>
        )}

        {termin.url !== null && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>URL</dt>
            <dd className="break-all">{termin.url}</dd>
          </div>
        )}

        {termin.notes !== null && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Notizen</dt>
            <dd className="whitespace-pre-wrap break-words">{termin.notes}</dd>
          </div>
        )}

        {termin.has_alarms && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Wecker</dt>
            <dd>{termin.alarms.map((a, i) => (
              <div key={i}>
                {a.absolute_date !== null
                  ? uhrzeit(a.absolute_date, zone)
                  : a.relative_offset_seconds !== null
                    ? `${Math.round(-a.relative_offset_seconds / 60)} Min. vorher`
                    : 'unbestimmt'}
              </div>
            ))}</dd>
          </div>
        )}

        {termin.has_attendees && (
          <div>
            <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
              Teilnehmer
            </dt>
            <dd>{termin.attendees.map((a, i) => (
              <div key={i} className="break-words">
                {a.display_name ?? a.raw_address ?? 'unbekannt'}
                {a.is_organizer && ' · Organisation'}
                <span style={{ color: 'var(--pjk-ink-dim)' }}>
                  {' '}· {a.participant_status}
                </span>
              </div>
            ))}</dd>
          </div>
        )}

        <div>
          <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>Status</dt>
          <dd>{termin.status} · {termin.availability}</dd>
        </div>
      </dl>

      {/* Der ehrliche Abschluss: was diese Ansicht kann und was nicht. */}
      <p className="mt-4 pt-2 text-[10px] leading-relaxed"
        style={{ color: 'var(--pjk-ink-dim)',
                 borderTop: '1px solid var(--pjk-line-soft)' }}>
        {termin.calendar_is_writable
          ? 'Bearbeiten ist in dieser Fassung noch nicht enthalten.'
          : 'Dieser Kalender ist beim Anbieter nicht beschreibbar — auch später wird er hier nicht bearbeitbar.'}
      </p>
    </aside>
  );
}

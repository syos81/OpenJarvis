// Mittlere Spalte: alphabetische Kontaktliste mit Abschnittsmarkern,
// stabiler Auswahl, vollständiger Tastaturbedienung und Fensterung.
//
// Fensterung: ab FENSTER_AB Zeilen werden nur die sichtbaren Zeilen (plus
// Überhang) in den DOM gestellt. Auswahl, Tastaturnavigation und die
// ARIA-Angaben (`aria-setsize`/`aria-posinset` je Option,
// `aria-activedescendant` am Listbox-Container) arbeiten auf der vollen
// Datenmenge und sind vom Fenster unabhängig.
//
// Solange keine Höhe gemessen ist, gilt `ANNAHME_VIEWPORT` statt „alles
// rendern". Das betrifft zwei reale Fälle: den ersten Render vor dem
// Messeffekt (Browser) und eine Umgebung ganz ohne Layout (jsdom meldet
// dauerhaft 0 Pixel). Vorher entstand in beiden Fällen der vollständige
// DOM — bei 10.000 Kontakten ein Baum, den niemand sieht und den der
// Browser sofort wieder verwirft. Die Annahme ist absichtlich grosszügig:
// sie deckt mehr als jeden üblichen Bildschirm ab, sodass vor der ersten
// Messung nichts Sichtbares fehlt.

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ContactSummary } from '../api';
import { abschnittsBuchstabe } from '../data/sortierung';
import { EmptyState } from '../components';

export const FENSTER_AB = 400;

/** Angenommene Sichthöhe in Pixeln, solange keine gemessen wurde. */
export const ANNAHME_VIEWPORT = 2000;

type Zeile =
  | { typ: 'abschnitt'; schluessel: string; buchstabe: string }
  | { typ: 'kontakt'; schluessel: string; kontakt: ContactSummary; pos: number };

function zeilenAufbauen(kontakte: ContactSummary[]): Zeile[] {
  const zeilen: Zeile[] = [];
  let aktuell = '';
  kontakte.forEach((kontakt, i) => {
    const b = abschnittsBuchstabe(kontakt);
    if (b !== aktuell) {
      aktuell = b;
      zeilen.push({ typ: 'abschnitt', schluessel: `s-${b}`, buchstabe: b });
    }
    zeilen.push({ typ: 'kontakt', schluessel: kontakt.id, kontakt, pos: i + 1 });
  });
  return zeilen;
}

export function initialen(name: string): string {
  const teile = name.trim().split(/\s+/).filter(Boolean);
  if (teile.length === 0) return '?';
  const erst = teile[0].charAt(0);
  const letzt = teile.length > 1 ? teile[teile.length - 1].charAt(0) : '';
  return (erst + letzt).toUpperCase();
}

function tokenPx(name: string, fallback: number): number {
  if (typeof window === 'undefined') return fallback;
  const roh = getComputedStyle(document.documentElement).getPropertyValue(name);
  const n = Number.parseFloat(roh);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      style={{
        flex: '0 0 auto',
        width: 'var(--pjc-avatar-list)',
        height: 'var(--pjc-avatar-list)',
        borderRadius: '50%',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        font: 'var(--pjc-font-label)',
        fontWeight: 600,
        color: 'var(--color-text-muted)',
        backgroundColor: 'var(--color-surface-2)',
      }}
    >
      {initialen(name)}
    </span>
  );
}

export function ContactsListPane({
  kontakte, auswahlId, onAuswahl, onEnterDetail, leerTitel, leerHinweis,
  testHoehe,
}: {
  kontakte: ContactSummary[];
  auswahlId: string | null;
  onAuswahl: (id: string) => void;
  onEnterDetail: () => void;
  leerTitel: string;
  leerHinweis?: string;
  /** Nur für Tests ohne Layout: erzwungene Viewport-Höhe in Pixeln. */
  testHoehe?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewport, setViewport] = useState(testHoehe ?? 0);
  const [fokussiert, setFokussiert] = useState(false);

  const zeilen = useMemo(() => zeilenAufbauen(kontakte), [kontakte]);
  const rowH = useMemo(() => tokenPx('--pjc-row-height', 36), []);
  const sectionH = useMemo(() => tokenPx('--pjc-section-height', 24), []);
  const overscan = useMemo(() => tokenPx('--pjc-list-overscan', 8), []);

  // Offsets je Zeile (Abschnitte und Kontakte sind unterschiedlich hoch).
  const offsets = useMemo(() => {
    const o = new Array<number>(zeilen.length + 1);
    o[0] = 0;
    zeilen.forEach((z, i) => {
      o[i + 1] = o[i] + (z.typ === 'abschnitt' ? sectionH : rowH);
    });
    return o;
  }, [zeilen, rowH, sectionH]);
  const gesamtHoehe = offsets[offsets.length - 1] ?? 0;

  useEffect(() => {
    if (testHoehe !== undefined) return undefined;
    const el = container.current;
    if (!el) return undefined;
    const messen = () => setViewport(el.clientHeight);
    messen();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(messen);
    ro.observe(el);
    return () => ro.disconnect();
  }, [testHoehe]);

  // Ungemessen heisst „noch nicht", nicht „unbegrenzt".
  const sichtHoehe = viewport > 0 ? viewport : ANNAHME_VIEWPORT;
  const fenstert = zeilen.length > FENSTER_AB;

  let von = 0;
  let bis = zeilen.length;
  if (fenstert) {
    // Binäre Suche nach der ersten sichtbaren Zeile.
    let lo = 0;
    let hi = zeilen.length - 1;
    while (lo < hi) {
      const mitte = (lo + hi) >> 1;
      if (offsets[mitte + 1] <= scrollTop) lo = mitte + 1; else hi = mitte;
    }
    von = Math.max(0, lo - overscan);
    let ende = lo;
    while (ende < zeilen.length && offsets[ende] < scrollTop + sichtHoehe) ende += 1;
    bis = Math.min(zeilen.length, ende + overscan);
  }

  const sichtbar = zeilen.slice(von, bis);

  const scrolleZu = (id: string) => {
    const el = container.current;
    if (!el) return;
    const idx = zeilen.findIndex((z) => z.typ === 'kontakt' && z.kontakt.id === id);
    if (idx === -1) return;
    const oben = offsets[idx];
    const unten = offsets[idx + 1];
    if (oben < el.scrollTop) el.scrollTop = oben - sectionH;
    else if (unten > el.scrollTop + el.clientHeight) {
      el.scrollTop = unten - el.clientHeight;
    }
  };

  const bewege = (richtung: 1 | -1 | 'anfang' | 'ende') => {
    if (kontakte.length === 0) return;
    const aktuell = kontakte.findIndex((k) => k.id === auswahlId);
    let ziel: number;
    if (richtung === 'anfang') ziel = 0;
    else if (richtung === 'ende') ziel = kontakte.length - 1;
    else if (aktuell === -1) ziel = richtung === 1 ? 0 : kontakte.length - 1;
    else ziel = Math.min(kontakte.length - 1, Math.max(0, aktuell + richtung));
    const id = kontakte[ziel].id;
    onAuswahl(id);
    scrolleZu(id);
  };

  if (kontakte.length === 0) {
    return (
      <div style={{ height: '100%', overflowY: 'auto', backgroundColor: 'var(--pjc-bg-list)' }}
           data-testid="contacts-liste-leer">
        <EmptyState title={leerTitel} hint={leerHinweis} />
      </div>
    );
  }

  return (
    <div
      role="listbox"
      aria-label="Kontakte"
      data-testid="contacts-liste"
      tabIndex={0}
      className="pjc-focusable"
      aria-activedescendant={auswahlId ? `pjc-opt-${auswahlId}` : undefined}
      onFocus={() => setFokussiert(true)}
      onBlur={() => setFokussiert(false)}
      onKeyDown={(e) => {
        if (e.key === 'ArrowDown') { e.preventDefault(); bewege(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); bewege(-1); }
        else if (e.key === 'Home') { e.preventDefault(); bewege('anfang'); }
        else if (e.key === 'End') { e.preventDefault(); bewege('ende'); }
        else if (e.key === 'Enter') { e.preventDefault(); onEnterDetail(); }
      }}
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--pjc-bg-list)',
        outlineOffset: '-2px',
      }}
    >
      {/* Eigener Scroll-Wrapper mit erzwungener Kompositions-Ebene:
          WKWebView auf macOS 12 liess den Scrollcontainer bei Layout-
          aenderungen von aussen (Trenner-Drag) und bei Hover-Zustaenden
          teils unneugezeichnet (Nutzerbefund 2026-08-02/03). */}
      <div
        ref={container}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: 'auto',
          transform: 'translateZ(0)',
        }}
      >
      <div style={{
        position: 'relative',
        height: fenstert ? `${gesamtHoehe}px` : undefined,
      }}>
        {sichtbar.map((zeile, i) => {
          const idx = von + i;
          const lage = fenstert ? {
            position: 'absolute' as const,
            top: `${offsets[idx]}px`,
            left: 0,
            right: 0,
          } : undefined;
          if (zeile.typ === 'abschnitt') {
            return (
              <div
                key={zeile.schluessel}
                role="presentation"
                aria-hidden="true"
                style={{
                  ...lage,
                  height: `${sectionH}px`,
                  display: 'flex',
                  alignItems: 'flex-end',
                  padding: '0 var(--pjc-pane-pad) 2px',
                  font: 'var(--pjc-font-section)',
                  color: 'var(--color-text-muted)',
                  backgroundColor: 'var(--pjc-bg-list)',
                }}
              >
                {zeile.buchstabe}
              </div>
            );
          }
          const k = zeile.kontakt;
          const gewaehlt = k.id === auswahlId;
          const letzte = idx === zeilen.length - 1;
          return (
            <div
              key={k.id}
              id={`pjc-opt-${k.id}`}
              role="option"
              aria-selected={gewaehlt}
              aria-setsize={kontakte.length}
              aria-posinset={zeile.pos}
              onClick={() => onAuswahl(k.id)}
              onDoubleClick={() => onAuswahl(k.id)}
              style={{
                ...lage,
                position: lage ? lage.position : 'relative',
                height: `${rowH}px`,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                // M2: die Auswahlflaeche laeuft ueber die volle Spaltenbreite,
                // eingerueckt wird der Inhalt. Vorher lag hier ein fester
                // 8px-Wert in der Komponente — Zahlen gehoeren in tokens.css.
                margin: 0,
                padding: '0 var(--pjc-row-inset-right) 0 var(--pjc-row-inset)',
                borderRadius: 'var(--pjc-radius-row)',
                cursor: 'default',
                color: gewaehlt && fokussiert
                  ? 'var(--pjc-selection-fg)' : 'var(--color-text)',
                backgroundColor: gewaehlt
                  ? (fokussiert ? 'var(--pjc-selection-bg)' : 'var(--pjc-selection-inactive-bg)')
                  : undefined,
              }}
            >
              {/* Zeilentrenner. M2: 1 pt, beginnt an der linken Avatarkante und
                  endet vor der Rollleiste. Als eigenes Element statt als
                  border-bottom, damit die gerundete Auswahlflaeche ihn
                  ueberdeckt statt ihn zu beschneiden. Die letzte Zeile bekommt
                  keinen — Apple schliesst die Liste ohne Abschlusslinie. */}
              {!gewaehlt && !letzte && (
                <span
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    left: 'var(--pjc-row-inset)',
                    right: 'var(--pjc-row-inset-right)',
                    bottom: 0,
                    height: 'var(--pjc-divider-width)',
                    backgroundColor: 'var(--pjc-divider)',
                    pointerEvents: 'none',
                  }}
                />
              )}
              <Avatar name={k.display_name} />
              <span style={{ minWidth: 0, flex: 1 }}>
                <span style={{
                  display: 'block',
                  font: 'var(--pjc-font-body)',
                  fontWeight: gewaehlt ? 600 : 400,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {k.display_name}
                </span>
                {k.organization_name && k.organization_name !== k.display_name && (
                  <span style={{
                    display: 'block',
                    font: 'var(--pjc-font-label)',
                    color: gewaehlt && fokussiert
                      ? 'var(--pjc-selection-fg)' : 'var(--color-text-muted)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}>
                    {k.organization_name}
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
      </div>
    </div>
  );
}

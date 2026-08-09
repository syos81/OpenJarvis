// Ziehbarer Spaltentrenner — Pointer und Tastatur gleichwertig.
//
// ARIA-Muster „window splitter": role="separator" mit vertikaler
// Orientierung, Wertebereich in Pixeln der links liegenden Spalte.
// Pfeil links/rechts ändert die Breite in festen Schritten; die Grenzen
// kommen aus den zentralen Tokens (Props), nie aus lokalen Zahlen.
//
// Beim Ziehen mit der Maus wird die neue Breite erst beim Loslassen
// angewendet; währenddessen zeigt eine Führungslinie die Zielposition.
// Das ist eine bewusste Monterey-Entscheidung: WKWebView auf macOS 12
// zeichnete live mitziehende Spalten unzuverlässig neu (Nutzerbefund
// 2026-08-02/03) — die verzögerte Anwendung ist dort glitchfrei.
// Tastaturschritte wenden sofort an.

import { useCallback, useRef, useState } from 'react';

const TASTATUR_SCHRITT = 16;

export function PaneDivider({ label, wert, min, max, onChange,
                              richtung = 'links' }: {
  label: string;
  wert: number;
  min: number;
  max: number;
  onChange: (breite: number) => void;
  /** B2: steuert der Trenner die LINKS oder die RECHTS liegende Spalte?
      Bei `rechts` waechst die Spalte beim Ziehen nach links — die
      Pfeiltasten folgen der Separatorbewegung, nicht dem Breitenwert. */
  richtung?: 'links' | 'rechts';
}) {
  const faktor = richtung === 'rechts' ? -1 : 1;
  const start = useRef<{ x: number; breite: number } | null>(null);
  const [ziehtZu, setZiehtZu] = useState<number | null>(null);

  const klemmen = useCallback(
    (b: number) => Math.min(max, Math.max(min, Math.round(b))),
    [min, max],
  );

  return (
    <div
        role="separator"
        aria-orientation="vertical"
        aria-label={label}
        aria-valuenow={Math.round(ziehtZu ?? wert)}
        aria-valuemin={min}
        aria-valuemax={max}
        tabIndex={0}
        className="pjc-focusable"
        style={{
          position: 'relative',
          flex: '0 0 auto',
          width: 'var(--pjc-divider-width)',
          height: '100%',
          cursor: 'col-resize',
          backgroundColor: 'var(--pjc-divider)',
          // Unsichtbar breitere Trefferfläche, ohne das Layout zu verschieben.
          boxSizing: 'content-box',
          paddingLeft: '3px',
          paddingRight: '3px',
          backgroundClip: 'content-box',
          touchAction: 'none',
        }}
        onPointerDown={(e) => {
          e.preventDefault();
          (e.target as HTMLElement).setPointerCapture(e.pointerId);
          start.current = { x: e.clientX, breite: wert };
          setZiehtZu(wert);
        }}
        onPointerMove={(e) => {
          if (!start.current) return;
          setZiehtZu(klemmen(
            start.current.breite + faktor * (e.clientX - start.current.x)));
        }}
        onPointerUp={(e) => {
          (e.target as HTMLElement).releasePointerCapture(e.pointerId);
          if (start.current && ziehtZu !== null) onChange(ziehtZu);
          start.current = null;
          setZiehtZu(null);
          // WKWebView (macOS 12): Neuzeichnung nach der Breitenänderung anstossen.
          window.dispatchEvent(new Event('resize'));
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') {
            e.preventDefault();
            onChange(klemmen(wert - faktor * TASTATUR_SCHRITT));
          } else if (e.key === 'ArrowRight') {
            e.preventDefault();
            onChange(klemmen(wert + faktor * TASTATUR_SCHRITT));
          } else if (e.key === 'Home') {
            e.preventDefault();
            onChange(min);
          } else if (e.key === 'End') {
            e.preventDefault();
            onChange(max);
          }
        }}
      >
      {ziehtZu !== null && (
        <div
          aria-hidden="true"
          style={{
            // Führungslinie an der Zielposition: Kind des Trenners,
            // horizontal um die Breitendifferenz versetzt.
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${(ziehtZu - wert) * faktor}px`,
            width: '2px',
            backgroundColor: 'var(--color-accent)',
            opacity: 0.7,
            pointerEvents: 'none',
            zIndex: 15,
          }}
        />
      )}
    </div>
  );
}

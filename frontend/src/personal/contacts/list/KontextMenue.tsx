/**
 * Kontextmenü der Kontaktliste — Rechtsklick auf eine Zeile.
 *
 * Die Referenz auf dem M2 zeigt dort sechs Einträge: Teilen, vCard
 * exportieren, Kontaktkarte bearbeiten, Kontakt blockieren, Kontaktkarte
 * löschen, mit Spotlight suchen. Übernommen werden **zwei** davon — die
 * beiden, hinter denen bei Jarvis tatsächlich etwas liegt. Teilen,
 * Blockieren und Spotlight sind Systemdienste des Apple-Ökosystems, und ein
 * vCard-Export existiert nicht; sie als Menüeintrag zu zeigen hiesse, eine
 * Fähigkeit zu behaupten, die das Produkt nicht hat.
 *
 * Die Einträge tragen dieselbe Fähigkeitsprüfung wie die Knöpfe im
 * Detailbereich (`is_me_card`, `writable`, `caps`). Ein Menü, das mehr
 * anbietet als der Rest der Oberfläche, wäre ein zweiter Wahrheitsstand.
 *
 * Ausgeführt wird hier nichts: beide Einträge münden in genau den
 * vorhandenen Weg über Vorbereitung, Vorschau und Freigabe.
 */

import { useEffect, useRef } from 'react';
import { Trash2 } from 'lucide-react';

export interface KontextEintrag {
  id: string;
  text: string;
  /** Zerstörerische Einträge tragen zusätzlich ein Symbol, wie in der Referenz. */
  gefaehrlich?: boolean;
  onAuswahl: () => void;
}

export function KontextMenue({ x, y, eintraege, onSchliessen }: {
  x: number;
  y: number;
  eintraege: KontextEintrag[];
  onSchliessen: () => void;
}) {
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Erster Eintrag bekommt den Fokus, damit das Menü sofort mit der
    // Tastatur bedienbar ist und nicht nur mit der Maus.
    panel.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();

    const aufTaste = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); onSchliessen(); return; }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      e.preventDefault();
      const liste = Array.from(
        panel.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
      if (liste.length === 0) return;
      const jetzt = liste.indexOf(document.activeElement as HTMLElement);
      const naechster = e.key === 'ArrowDown'
        ? (jetzt + 1) % liste.length
        : (jetzt <= 0 ? liste.length - 1 : jetzt - 1);
      liste[naechster]?.focus();
    };
    // Ein Klick daneben, ein Scrollen oder ein Fensterwechsel schliesst —
    // ein stehengebliebenes Menü über einer veränderten Liste zeigt sonst
    // Aktionen zu einem Kontakt, den der Mensch gar nicht mehr meint.
    const zu = () => onSchliessen();
    document.addEventListener('keydown', aufTaste);
    document.addEventListener('mousedown', zu);
    window.addEventListener('resize', zu);
    window.addEventListener('blur', zu);
    document.addEventListener('scroll', zu, true);
    return () => {
      document.removeEventListener('keydown', aufTaste);
      document.removeEventListener('mousedown', zu);
      window.removeEventListener('resize', zu);
      window.removeEventListener('blur', zu);
      document.removeEventListener('scroll', zu, true);
    };
  }, [onSchliessen]);

  if (eintraege.length === 0) return null;

  return (
    <div
      ref={panel}
      role="menu"
      aria-label="Kontaktaktionen"
      data-testid="kontakt-kontextmenue"
      // Der Klick auf einen Eintrag darf nicht als "daneben" gelten.
      onMouseDown={(e) => e.stopPropagation()}
      style={{
        position: 'fixed',
        left: `${x}px`,
        top: `${y}px`,
        zIndex: 60,
        minWidth: '220px',
        padding: '4px',
        background: 'var(--color-surface)',
        border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
        borderRadius: 'var(--pjc-menu-radius)',
        boxShadow: 'var(--shadow-lg, 0 8px 24px rgba(0,0,0,0.18))',
      }}
    >
      {eintraege.map((e) => (
        <button
          key={e.id}
          type="button"
          role="menuitem"
          data-testid={`kontextmenue-${e.id}`}
          className="pjc-focusable"
          onClick={() => { e.onAuswahl(); onSchliessen(); }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            width: '100%',
            height: 'var(--pjc-menu-row-height)',
            padding: '0 8px',
            border: 'none',
            background: 'transparent',
            borderRadius: 'calc(var(--pjc-menu-radius) - 2px)',
            font: 'var(--pjc-font-body)',
            color: 'var(--color-text)',
            textAlign: 'left',
          }}
        >
          {e.gefaehrlich && (
            <Trash2 size={14} aria-hidden="true" style={{ flex: '0 0 auto' }} />
          )}
          <span>{e.text}</span>
        </button>
      ))}
    </div>
  );
}

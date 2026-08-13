// Kontakte-Toolbar: ruhige macOS-Anmutung — Suchfeld, Neuanlage (nur wenn
// der Provider sie meldet), Zugang zur Statusfläche. Keine generische
// Web-Headerleiste, keine dauerhafte Entwicklerdiagnose.

import { forwardRef } from 'react';
import { PanelLeft, Plus, Search, X } from 'lucide-react';
import { aktionsKnopf } from '../detail/ContactDetailPane';

export const ContactsToolbar = forwardRef<HTMLInputElement, {
  /** Ist die linke Seitenleiste eingeblendet? */
  seitenleisteOffen: boolean;
  /** Blendet sie ein oder aus — macOS-Konvention: Knopf ganz links. */
  onSeitenleiste: () => void;
  suche: string;
  onSuche: (wert: string) => void;
  onSucheEscape: () => void;
  /**
   * Ob Anlegen tatsaechlich moeglich ist. `false` blendet die Aktion
   * **nicht** aus: Eine Oberflaeche, in der Schreibfunktionen bei fehlender
   * Freigabe spurlos verschwinden, sieht aus, als gaebe es sie gar nicht —
   * und laesst den Eigentuemer ohne Weg zur Freigabe zurueck (§I).
   */
  anlegenMoeglich: boolean;
  /** Das Plus oeffnet wie in der Referenz ein Menue, keinen Dialog direkt. */
  onAnlegen: (x: number, y: number) => void;
  /** Erklaert den gesperrten Zustand — nie eine Selbstfreigabe. */
  onGesperrt: () => void;
  /** „Bearbeiten" steht wie in der Referenz oben rechts, nicht in der Karte. */
  bearbeitenSichtbar: boolean;
  onBearbeiten: () => void;
  demoModus: boolean;
}>(function ContactsToolbar({
  seitenleisteOffen, onSeitenleiste,
  suche, onSuche, onSucheEscape, anlegenMoeglich, onAnlegen, onGesperrt,
  bearbeitenSichtbar, onBearbeiten,
  demoModus,
}, suchfeldRef) {
  return (
    <div
      role="toolbar"
      aria-label="Kontakte-Werkzeuge"
      style={{
        height: 'var(--pjc-toolbar-height)',
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--pjc-toolbar-gap)',
        padding: '0 var(--pjc-toolbar-reserve) 0 var(--pjc-pane-pad)',
        borderBottom: 'var(--pjc-divider-width) solid var(--pjc-divider)',
        backgroundColor: 'var(--pjc-bg-list)',
        flex: '0 0 auto',
      }}
    >
      {/* Ganz links, wie in den Systemapps. Der Zustand steht in
          aria-pressed, damit er auch ohne Blick auf das Symbol lesbar ist. */}
      <button type="button" className="pjc-focusable"
              onClick={onSeitenleiste}
              data-testid="seitenleiste-toggle"
              aria-pressed={seitenleisteOffen}
              aria-label={seitenleisteOffen
                ? 'Seitenleiste ausblenden' : 'Seitenleiste einblenden'}
              title={seitenleisteOffen
                ? 'Seitenleiste ausblenden' : 'Seitenleiste einblenden'}
              style={{
                ...aktionsKnopf(false), display: 'inline-flex',
                alignItems: 'center',
                opacity: seitenleisteOffen ? 1 : 0.55,
              }}>
        <PanelLeft size={15} aria-hidden="true" />
      </button>

      <h1 style={{ font: 'var(--pjc-font-title)', fontSize: '0.9375rem', margin: 0 }}>
        Kontakte
      </h1>

      {demoModus && (
        <span
          data-testid="demo-banner"
          style={{
            font: 'var(--pjc-font-label)',
            color: 'var(--color-warning)',
            border: 'var(--pjc-divider-width) solid var(--color-warning)',
            borderRadius: '999px',
            padding: '1px 8px',
          }}
        >
          Demo-Modus: synthetische Kontakte
        </span>
      )}

      <div style={{ flex: 1 }} />

      {bearbeitenSichtbar && (
        <button type="button" onClick={onBearbeiten} className="pjc-focusable"
                data-testid="toolbar-bearbeiten"
                style={aktionsKnopf(false)}>
          Bearbeiten
        </button>
      )}

      {/* Immer da. Gesperrt fuehrt es zur Erklaerung, nicht ins Leere: Der
          Eigentuemer soll sehen, dass Schreiben existiert und derzeit
          gesperrt ist — und wie es freigegeben wird. */}
      <button type="button" className="pjc-focusable"
              onClick={(e) => {
                if (!anlegenMoeglich) { onGesperrt(); return; }
                const r = e.currentTarget.getBoundingClientRect();
                onAnlegen(r.left, r.bottom + 4);
              }}
              data-testid="toolbar-anlegen"
              data-gesperrt={anlegenMoeglich ? undefined : 'true'}
              aria-label={anlegenMoeglich ? 'Neu' : 'Neu — Schreiben gesperrt'}
              aria-haspopup={anlegenMoeglich ? 'menu' : 'dialog'}
              title={anlegenMoeglich ? undefined
                : 'Schreiben ist gesperrt — hier erfaehrst du, warum'}
              style={{
                ...aktionsKnopf(false), display: 'inline-flex',
                alignItems: 'center', gap: '4px',
                opacity: anlegenMoeglich ? 1 : 0.45,
              }}>
        <Plus size={15} aria-hidden="true" />
      </button>

      <div style={{ position: 'relative' }}>
        <Search
          size={13}
          aria-hidden="true"
          style={{
            position: 'absolute', left: '8px', top: '50%',
            transform: 'translateY(-50%)',
            color: 'var(--color-text-muted)', pointerEvents: 'none',
          }}
        />
        <input
          ref={suchfeldRef}
          type="search"
          value={suche}
          onChange={(e) => onSuche(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              onSucheEscape();
            }
          }}
          placeholder="Suchen"
          aria-label="Kontakte durchsuchen"
          data-testid="toolbar-suche"
          className="pjc-focusable"
          style={{
            font: 'var(--pjc-font-body)',
            width: 'var(--pjc-search-width)',
            border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
            borderRadius: 'var(--pjc-radius-control)',
            padding: '3px 8px 3px 26px',
            minHeight: 'var(--pjc-hit-target)',
            background: 'transparent',
            color: 'var(--color-text)',
          }}
        />
        {suche !== '' && (
          <button
            type="button"
            aria-label="Suche löschen"
            onClick={() => onSuche('')}
            className="pjc-focusable"
            style={{
              position: 'absolute', right: '2px', top: '50%',
              transform: 'translateY(-50%)',
              border: 'none', background: 'none',
              color: 'var(--color-text-muted)',
              minWidth: 'var(--pjc-hit-target)', minHeight: 'var(--pjc-hit-target)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <X size={12} aria-hidden="true" />
          </button>
        )}
      </div>

      {/* Der Zugang zu Vorgängen und Status ist aus der Toolbar verschwunden
          und steht jetzt unten in der Seitenleiste — die Referenz hat oben
          rechts nichts dergleichen. */}
    </div>
  );
});

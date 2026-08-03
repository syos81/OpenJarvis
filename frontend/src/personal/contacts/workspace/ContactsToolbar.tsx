// Kontakte-Toolbar: ruhige macOS-Anmutung — Suchfeld, Neuanlage (nur wenn
// der Provider sie meldet), Zugang zur Statusfläche. Keine generische
// Web-Headerleiste, keine dauerhafte Entwicklerdiagnose.

import { forwardRef } from 'react';
import { ClipboardList, Plus, Search, X } from 'lucide-react';
import { aktionsKnopf } from '../detail/ContactDetailPane';

export const ContactsToolbar = forwardRef<HTMLInputElement, {
  suche: string;
  onSuche: (wert: string) => void;
  onSucheEscape: () => void;
  anlegenSichtbar: boolean;
  onAnlegen: () => void;
  statusOffen: boolean;
  onStatusToggle: () => void;
  demoModus: boolean;
  offeneFreigaben: number;
}>(function ContactsToolbar({
  suche, onSuche, onSucheEscape, anlegenSichtbar, onAnlegen,
  statusOffen, onStatusToggle, demoModus, offeneFreigaben,
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

      {anlegenSichtbar && (
        <button type="button" onClick={onAnlegen} className="pjc-focusable"
                data-testid="toolbar-anlegen"
                aria-label="Kontakt anlegen"
                style={{ ...aktionsKnopf(false), display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
          <Plus size={15} aria-hidden="true" />
        </button>
      )}

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
              border: 'none', background: 'none', cursor: 'default',
              color: 'var(--color-text-muted)',
              minWidth: 'var(--pjc-hit-target)', minHeight: 'var(--pjc-hit-target)',
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <X size={12} aria-hidden="true" />
          </button>
        )}
      </div>

      <button
        type="button"
        onClick={onStatusToggle}
        aria-label={`Vorgänge und Status ${statusOffen ? 'schliessen' : 'öffnen'}`}
        aria-expanded={statusOffen}
        data-testid="toolbar-status"
        className="pjc-focusable"
        style={{
          ...aktionsKnopf(false),
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          color: statusOffen ? 'var(--color-accent)' : 'var(--color-text)',
        }}
      >
        <ClipboardList size={15} aria-hidden="true" />
        {offeneFreigaben > 0 && (
          <span
            aria-label={`${offeneFreigaben} offene Freigaben`}
            style={{
              font: 'var(--pjc-font-label)',
              color: 'var(--color-warning)',
              fontWeight: 600,
            }}
          >
            {offeneFreigaben}
          </span>
        )}
      </button>
    </div>
  );
});

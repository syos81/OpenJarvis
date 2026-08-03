// Linke Seitenleiste: „Alle Kontakte", Konten, lokale Kategorien.
//
// Kompakte Apple-Struktur: Abschnittsköpfe in Kapitälchen, schmale Zeilen,
// eine klar markierte Auswahl. Konten erscheinen ausschliesslich als
// maskierte Referenzen-Anzahl-Filter — Provider-Identifier haben hier
// nichts verloren, deshalb tragen die Zeilen neutrale Namen („Konto 1").

import type { RoleCount } from '../api';

export type SidebarAuswahl =
  | { art: 'alle' }
  | { art: 'konto'; ref: string }
  | { art: 'kategorie'; rolle: string };

export function sidebarAuswahlGleich(a: SidebarAuswahl, b: SidebarAuswahl): boolean {
  if (a.art !== b.art) return false;
  if (a.art === 'konto' && b.art === 'konto') return a.ref === b.ref;
  if (a.art === 'kategorie' && b.art === 'kategorie') return a.rolle === b.rolle;
  return true;
}

function SidebarSection({ titel, children }: {
  titel: string; children: React.ReactNode;
}) {
  return (
    <section aria-label={titel} style={{ marginTop: 'var(--pjc-detail-gap)' }}>
      <h3 style={{
        font: 'var(--pjc-font-section)',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        color: 'var(--color-text-muted)',
        padding: '0 var(--pjc-pane-pad) 4px',
        margin: 0,
      }}>
        {titel}
      </h3>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>{children}</ul>
    </section>
  );
}

function SidebarRow({ label, anzahl, aktiv, onSelect, testId }: {
  label: string;
  anzahl?: number;
  aktiv: boolean;
  onSelect: () => void;
  testId?: string;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={aktiv ? 'true' : undefined}
        data-testid={testId}
        className="pjc-focusable"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
          width: `calc(100% - 2 * var(--pjc-pane-pad) + 8px)`,
          margin: '0 calc(var(--pjc-pane-pad) - 4px)',
          minHeight: 'var(--pjc-sidebar-row-height)',
          padding: '0 8px',
          border: 'none',
          borderRadius: 'var(--pjc-radius-row)',
          font: 'var(--pjc-font-body)',
          textAlign: 'left',
          color: aktiv ? 'var(--pjc-selection-fg)' : 'var(--color-text)',
          backgroundColor: aktiv ? 'var(--pjc-selection-bg)' : 'transparent',
          cursor: 'default',
        }}
      >
        <span style={{
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontWeight: aktiv ? 600 : 400,
        }}>
          {label}
        </span>
        {anzahl !== undefined && (
          <span style={{
            font: 'var(--pjc-font-label)',
            color: aktiv ? 'var(--pjc-selection-fg)' : 'var(--color-text-muted)',
          }}>
            {anzahl}
          </span>
        )}
      </button>
    </li>
  );
}

export function ContactsSidebar({
  auswahl, onAuswahl, konten, kategorien, gesamt, demoModus,
}: {
  auswahl: SidebarAuswahl;
  onAuswahl: (a: SidebarAuswahl) => void;
  konten: string[];
  kategorien: RoleCount[];
  gesamt: number;
  demoModus: boolean;
}) {
  return (
    <nav
      aria-label="Kontaktquellen und Gruppen"
      data-testid="contacts-sidebar"
      style={{
        height: '100%',
        overflowY: 'auto',
        backgroundColor: 'var(--pjc-bg-sidebar)',
        paddingTop: 'var(--pjc-pane-pad)',
        paddingBottom: 'var(--pjc-pane-pad)',
      }}
    >
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        <SidebarRow
          label="Alle Kontakte"
          anzahl={gesamt}
          aktiv={auswahl.art === 'alle'}
          onSelect={() => onAuswahl({ art: 'alle' })}
          testId="sidebar-alle"
        />
      </ul>

      {konten.length > 1 && (
        <SidebarSection titel="Konten">
          {konten.map((ref, i) => (
            <SidebarRow
              key={ref}
              label={demoModus ? `Demo-Konto ${i + 1}` : `Konto ${i + 1}`}
              aktiv={auswahl.art === 'konto' && auswahl.ref === ref}
              onSelect={() => onAuswahl({ art: 'konto', ref })}
            />
          ))}
        </SidebarSection>
      )}

      {kategorien.length > 0 && (
        <SidebarSection titel="Kategorien">
          {kategorien.map((k) => (
            <SidebarRow
              key={k.role}
              label={k.role}
              anzahl={k.count}
              aktiv={auswahl.art === 'kategorie' && auswahl.rolle === k.role}
              onSelect={() => onAuswahl({ art: 'kategorie', rolle: k.role })}
            />
          ))}
        </SidebarSection>
      )}
    </nav>
  );
}

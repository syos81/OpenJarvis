// Bausteine der Kontakte-Oberfläche.
//
// Bewusst im bestehenden Jarvis-Look: dieselben CSS-Variablen, dieselbe
// Typografie, dieselben shadcn-Bausteine wie die übrigen Seiten. Es entsteht
// keine zweite Designwelt.

import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, Info, Loader2, ShieldAlert } from 'lucide-react';
import type { FieldAvailability, FieldState } from './api';

// ── Zustandsflächen ────────────────────────────────────────────────────────
export function LoadingState({ label }: { label: string }) {
  return (
    <div
      className="flex items-center gap-2 py-8 justify-center text-sm"
      style={{ color: 'var(--color-text-muted)' }}
      role="status"
      aria-live="polite"
    >
      <Loader2 size={16} className="animate-spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, hint, action }: {
  title: string; hint?: string; action?: ReactNode;
}) {
  return (
    <div className="py-12 text-center" role="status">
      <p className="text-sm font-medium">{title}</p>
      {hint && (
        <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
          {hint}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * Fehlerfläche mit drei getrennten Aussagen.
 *
 * Vorher stand hier nur die Nachricht — und wenn der Server einen
 * Ausnahmeklassennamen lieferte, las der Nutzer wörtlich
 * „BridgeOperationError". Das sagt ihm nichts, verrät nicht, ob ein zweiter
 * Versuch etwas bringt, und ist für die Fehlersuche wertlos, weil der Name
 * nicht sagt, welcher Schritt scheiterte.
 *
 * Jetzt trägt die Fläche: einen Satz für den Menschen, den Hinweis auf
 * Wiederholbarkeit, und — klein und abgesetzt — die stabile technische
 * Kennung zum Weitergeben. Keine Pfade, keine Kontaktdaten.
 */
export function ErrorState({ message, code, technicalCode, retryable, onRetry }: {
  message: string;
  code?: string;
  technicalCode?: string;
  retryable?: boolean;
  onRetry?: () => void;
}) {
  const kennung = [code, technicalCode]
    .filter((t) => t && t.length > 0)
    .filter((t, i, a) => a.indexOf(t) === i)
    .join(' · ');
  return (
    <div
      className="my-4 rounded-md border p-4 text-sm"
      style={{ borderColor: 'var(--color-danger, #b91c1c)' }}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="font-medium">{message}</p>
          {retryable !== undefined && (
            <p className="mt-1" style={{ color: 'var(--color-text-muted)' }}>
              {retryable
                ? 'Ein erneuter Versuch kann helfen.'
                : 'Ein erneuter Versuch ändert daran nichts.'}
            </p>
          )}
          {kennung && (
            <p className="mt-2 font-mono text-xs" data-testid="fehler-kennung"
               style={{ color: 'var(--color-text-muted)' }}>
              Code: {kennung}
            </p>
          )}
          {onRetry && (
            <button type="button" onClick={onRetry} className="mt-3 underline">
              Erneut laden
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Feldverfügbarkeit ──────────────────────────────────────────────────────
/**
 * Zeigt an, warum ein Feld nichts enthält.
 *
 * `unavailable_by_capability` darf **nie** wie ein leeres Feld aussehen: die
 * Notiz existiert womöglich, wir dürfen sie nur nicht lesen. Wer das
 * verwechselt, überschreibt beim nächsten Schreibvorgang fremde Daten.
 */
export function FieldStateBadge({ state }: { state: FieldState }) {
  if (state === 'present') return null;
  const unavailable = state === 'unavailable_by_capability';
  return (
    <span
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs"
      style={{
        backgroundColor: 'var(--color-surface-2, rgba(127,127,127,0.12))',
        color: 'var(--color-text-muted)',
      }}
      title={
        unavailable
          ? 'Dieses Feld kann nicht gelesen werden. Ob es einen Inhalt hat, ist unbekannt — es gilt nicht als leer.'
          : 'Der Provider hat dieses Feld geliefert; es ist leer.'
      }
    >
      {unavailable ? <ShieldAlert size={12} aria-hidden="true" /> : <Info size={12} aria-hidden="true" />}
      {unavailable ? 'nicht lesbar' : 'leer'}
    </span>
  );
}

export function availabilityOf(
  list: FieldAvailability[], field: string,
): FieldState | null {
  return list.find((f) => f.field_name === field)?.state ?? null;
}

// ── Kleinteile ─────────────────────────────────────────────────────────────
export function Chip({ children, tone = 'neutral', title }: {
  children: ReactNode; tone?: 'neutral' | 'warn' | 'info'; title?: string;
}) {
  const farben: Record<string, string> = {
    neutral: 'var(--color-text-muted)',
    warn: 'var(--color-warning, #b45309)',
    info: 'var(--color-accent)',
  };
  return (
    <span
      className="inline-flex items-center rounded-full border px-2 py-0.5 text-xs"
      style={{ color: farben[tone], borderColor: 'currentColor' }}
      title={title}
    >
      {children}
    </span>
  );
}

/** Deutsche Beschriftung eines Mutationszustands. */
export const MUTATION_LABELS: Record<string, string> = {
  prepared: 'Vorbereitet',
  awaiting_approval: 'Wartet auf Freigabe',
  approved: 'Freigegeben',
  rejected: 'Abgelehnt',
  expired: 'Abgelaufen',
  cancelled: 'Abgebrochen',
  executing: 'Wird ausgeführt',
  succeeded: 'Erfolgreich',
  failed_before_send: 'Fehlgeschlagen, nichts gesendet',
  outcome_unknown: 'Ausgang unbekannt',
  reconcile_required: 'Abgleich nötig',
  manual_decision_required: 'Entscheidung nötig',
  failed: 'Fehlgeschlagen',
};

export const COMMAND_LABELS: Record<string, string> = {
  create: 'Anlegen',
  update: 'Ändern',
  delete: 'Löschen',
};

/**
 * Beschriftung der Ablageortarten. Wortgleich mit dem geschlossenen Vorrat in
 * `sync/containers.py` (`SPECIFIC_CONTAINER_TYPES`).
 *
 * Stand bis 2026-08-13 nur im Anlagedialog. Seit die Freigabevorschau den
 * Zielort ebenfalls nennt, ist das eine gemeinsame Sache: Zwei Tabellen wären
 * zwei Wahrheiten darüber, wie „local" heisst — und ausgerechnet an der
 * Stelle, an der der Mensch entscheidet, wohin geschrieben wird.
 */
export const CONTAINER_ART: Record<string, string> = {
  local: 'Lokal · Auf meinem Mac',
  cardDAV: 'CardDAV / iCloud',
  exchange: 'Exchange',
  unassigned: 'Ohne Zuordnung',
  unknown: 'Art noch nicht bekannt',
};

/**
 * Die Zielangabe einer freigabepflichtigen Mutation: Operation, Zielobjekt,
 * Ablageort mit Art und stabiler Kennung.
 *
 * Sie ist Bestandteil der informierten Eigentümerfreigabe (§8 A) und keine
 * Verzierung — ohne sie beantwortet die Vorschau „wohin" nicht. Der
 * Vorschau-Digest deckt Ablageort **und** Art; angezeigt wird ausschliesslich
 * die maskierte Kennung, nie die rohe Providerkennung.
 */
export function Zielangabe({ command, targetLabel, containerRef, containerType }: {
  command: string;
  targetLabel?: string | null;
  containerRef?: string | null;
  containerType?: string | null;
}) {
  const art = containerType ?? 'unknown';
  return (
    <dl data-testid="zielangabe" style={{
      display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px',
      font: 'var(--pjc-font-body)', margin: 0,
    }}>
      <dt style={{ color: 'var(--color-text-muted)' }}>Operation</dt>
      <dd style={{ margin: 0, fontWeight: 600 }}>
        {COMMAND_LABELS[command] ?? command}
      </dd>
      {targetLabel && (
        <>
          <dt style={{ color: 'var(--color-text-muted)' }}>Ziel</dt>
          <dd style={{ margin: 0 }}>{targetLabel}</dd>
        </>
      )}
      <dt style={{ color: 'var(--color-text-muted)' }}>Ablageort</dt>
      <dd style={{ margin: 0 }}>
        {CONTAINER_ART[art] ?? art}
        {containerRef && (
          <>
            {' '}
            <span style={{ color: 'var(--color-text-muted)' }}>
              {art} {containerRef}
            </span>
          </>
        )}
        {!containerRef && (
          <span style={{ color: 'var(--color-text-muted)' }}>
            {' '}— nicht bestimmbar
          </span>
        )}
      </dd>
    </dl>
  );
}

export function StateChip({ state }: { state: string }) {
  const warnend = ['outcome_unknown', 'reconcile_required',
    'manual_decision_required', 'failed', 'rejected', 'expired'];
  const tone = warnend.includes(state) ? 'warn'
    : state === 'succeeded' ? 'info' : 'neutral';
  return <Chip tone={tone}>{MUTATION_LABELS[state] ?? state}</Chip>;
}

// ── Dialog mit Fokusfalle ──────────────────────────────────────────────────
/**
 * Modaler Dialog mit vollständiger Tastaturbedienung.
 *
 * Der Fokus wandert beim Öffnen hinein, bleibt beim Tabben innerhalb, kehrt
 * beim Schließen zum auslösenden Element zurück, und Escape schließt.
 */
export function Modal({ open, onClose, title, description, children, footer }: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const vorher = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return undefined;
    vorher.current = document.activeElement as HTMLElement | null;
    const knoten = panel.current;
    // Sichtbarkeit bewusst NICHT über `offsetParent` prüfen: die Eigenschaft
    // ist in Testumgebungen ohne Layout immer `null`, wodurch die Liste leer
    // bliebe und die Fokusfalle unbemerkt wirkungslos wäre. Geprüft wird
    // stattdessen, was der Dialog selbst kontrolliert.
    const fokussierbare = () =>
      Array.from(
        knoten?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((e) => !e.hidden
        && e.getAttribute('aria-hidden') !== 'true'
        && e.closest('[hidden]') === null);

    fokussierbare()[0]?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;
      const liste = fokussierbare();
      if (liste.length === 0) return;
      const erster = liste[0];
      const letzter = liste[liste.length - 1];
      if (e.shiftKey && document.activeElement === erster) {
        e.preventDefault();
        letzter.focus();
      } else if (!e.shiftKey && document.activeElement === letzter) {
        e.preventDefault();
        erster.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      vorher.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="pj-modal-title"
        aria-describedby={description ? 'pj-modal-desc' : undefined}
        className="w-full max-w-2xl overflow-auto rounded-lg border p-5 shadow-lg"
        style={{
          maxHeight: '85vh',
          backgroundColor: 'var(--color-surface, #111)',
          borderColor: 'var(--color-border, rgba(127,127,127,0.3))',
        }}
      >
        <h2 id="pj-modal-title" className="text-base font-semibold">{title}</h2>
        {description && (
          <p id="pj-modal-desc" className="mt-1 text-sm"
             style={{ color: 'var(--color-text-muted)' }}>
            {description}
          </p>
        )}
        <div className="mt-4">{children}</div>
        {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

// ── Vorher/Nachher ─────────────────────────────────────────────────────────
export function ChangeTable({ changes }: {
  changes: { field_name: string; previous: unknown; planned: unknown }[];
}) {
  if (changes.length === 0) {
    return (
      <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>
        Keine Feldänderung.
      </p>
    );
  }
  const zeige = (v: unknown) =>
    v === null || v === undefined || v === ''
      ? '—'
      : typeof v === 'object' ? JSON.stringify(v) : String(v);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Geplante Änderungen, vorher und nachher</caption>
        <thead>
          <tr style={{ color: 'var(--color-text-muted)' }}>
            <th scope="col" className="py-1 text-left font-medium">Feld</th>
            <th scope="col" className="py-1 text-left font-medium">Bisher</th>
            <th scope="col" className="py-1 text-left font-medium">Geplant</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={c.field_name} className="border-t"
                style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}>
              <th scope="row" className="py-1.5 pr-3 text-left font-normal">{c.field_name}</th>
              <td className="py-1.5 pr-3" style={{ color: 'var(--color-text-muted)' }}>
                {zeige(c.previous)}
              </td>
              <td className="py-1.5 font-medium">{zeige(c.planned)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

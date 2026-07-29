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

export function ErrorState({ message, onRetry }: {
  message: string; onRetry?: () => void;
}) {
  return (
    <div
      className="my-4 rounded-md border p-4 text-sm"
      style={{ borderColor: 'var(--color-danger, #b91c1c)' }}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={16} aria-hidden="true" className="mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="font-medium">Die Anfrage ist fehlgeschlagen.</p>
          <p className="mt-1" style={{ color: 'var(--color-text-muted)' }}>{message}</p>
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
    const fokussierbare = () =>
      Array.from(
        knoten?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      ).filter((e) => e.offsetParent !== null);

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

// Jarvis Core v0 — sichtbare Command Bar.
//
// Die Oberfläche kennt keinen einzigen Befehl. Sie nimmt Text entgegen,
// übergibt ihn an den lokalen Router und zeigt dessen Zeilen an. Damit
// bleibt der Router die einzige Stelle, die entscheidet, was Jarvis kann.

import { useEffect, useRef, useState } from 'react';
import { routeCommand, type CoreContext, type CoreResult } from './commandRouter';

export function JarvisCommandBar({ context, onClose }: {
  context: CoreContext;
  onClose: () => void;
}) {
  const [eingabe, setEingabe] = useState('');
  const [ergebnis, setErgebnis] = useState<CoreResult | null>(null);
  const feld = useRef<HTMLInputElement>(null);

  useEffect(() => {
    feld.current?.focus();
  }, []);

  // Escape schliesst — auf Dokumentebene, damit es unabhängig davon wirkt,
  // wo der Fokus gerade steht. Gleiches Muster wie der Dialog der Kontakte.
  useEffect(() => {
    const aufTaste = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      onClose();
    };
    document.addEventListener('keydown', aufTaste);
    return () => document.removeEventListener('keydown', aufTaste);
  }, [onClose]);

  const ausfuehren = (e: React.SyntheticEvent) => {
    e.preventDefault();
    setErgebnis(routeCommand(eingabe, context));
  };

  // Enter wird ausdrücklich behandelt statt auf die implizite Absendung des
  // Formulars zu bauen: die greift nur unter Bedingungen, die eine spätere
  // Änderung am Formular unbemerkt aushebeln würde.
  const aufFeldTaste = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== 'Enter') return;
    ausfuehren(e);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="fixed inset-0" style={{ background: 'rgba(0,0,0,0.5)' }} aria-hidden="true" />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Jarvis Command Bar"
        className="relative w-full max-w-lg rounded-xl overflow-hidden"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <form onSubmit={ausfuehren}>
          <div
            className="flex items-center gap-3 px-4 py-3"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <span className="text-xs font-mono shrink-0" style={{ color: 'var(--color-accent)' }}>
              jarvis
            </span>
            <input
              ref={feld}
              type="text"
              value={eingabe}
              onChange={(e) => setEingabe(e.target.value)}
              onKeyDown={aufFeldTaste}
              aria-label="Befehl"
              placeholder="Befehl eingeben — help zeigt alles Vorhandene"
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: 'var(--color-text)' }}
            />
          </div>
        </form>

        {ergebnis && (
          <div
            className="px-4 py-3 flex flex-col gap-1"
            role="status"
            aria-live="polite"
            data-testid="jarvis-core-result"
            data-kind={ergebnis.kind}
          >
            {ergebnis.lines.map((zeile, i) => (
              <div
                key={`${i}-${zeile}`}
                className="text-sm font-mono"
                style={{
                  color: i === 0 && ergebnis.kind !== 'unknown'
                    ? 'var(--color-text)'
                    : 'var(--color-text-tertiary)',
                }}
              >
                {zeile}
              </div>
            ))}
          </div>
        )}

        <div
          className="flex items-center gap-4 px-4 py-2 text-[11px]"
          style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          <span><kbd className="font-mono">Enter</kbd> Ausführen</span>
          <span><kbd className="font-mono">Esc</kbd> Schliessen</span>
          <span className="ml-auto">lokal — kein Netzwerk</span>
        </div>
      </div>
    </div>
  );
}

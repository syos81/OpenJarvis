// Der Schalter, mit dem Lukas das Schreiben in seine Kontakte einschaltet.
//
// Bis hierher war die Erteilung eine Datei, die von Hand entstehen musste, und
// sie lief nach vier Stunden ab. Für einen Alltagsgebrauch war das keine
// Freigabe, sondern eine Zeremonie.
//
// Drei Eigenschaften, die dieser Schalter ausdrücklich hat:
//
//   * **Einschalten verlangt eine Systemauthentifizierung.** Touch ID oder das
//     Anmeldekennwort — die Entscheidung trifft macOS, nicht Jarvis.
//   * **Ausschalten verlangt keine.** Wer Rechte verringert, soll es leicht
//     haben; eine Hürde davor machte den sicheren Weg teurer als den anderen.
//   * **Er sagt, was er erteilt.** `create` und `update` je genau eines
//     Kontakts. Kein Löschen, keine Massenänderung.

import { useCallback, useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';

import {
  AUS,
  grundText,
  leseZustand,
  schalteAus,
  schalteEin,
  type StandingWriteState,
} from './schreibfreigabe';

export function SchreibfreigabeSchalter() {
  const [zustand, setZustand] = useState<StandingWriteState>(AUS);
  const [laeuft, setLaeuft] = useState(false);
  const [geladen, setGeladen] = useState(false);

  useEffect(() => {
    let lebt = true;
    leseZustand().then((z) => {
      if (lebt) { setZustand({ ...z, reason_code: null }); setGeladen(true); }
    });
    return () => { lebt = false; };
  }, []);

  const umschalten = useCallback(async () => {
    setLaeuft(true);
    try {
      setZustand(zustand.standing ? await schalteAus() : await schalteEin());
    } finally {
      setLaeuft(false);
    }
  }, [zustand.standing]);

  const hinweis = grundText(zustand.reason_code);
  const an = zustand.standing;

  return (
    <div data-testid="contacts-schreibfreigabe">
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '16px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text)' }}>
            Kontakte dauerhaft schreiben
          </div>
          <p style={{
            margin: '4px 0 0', font: 'var(--pjc-font-label)',
            color: 'var(--color-text-secondary)',
          }}>
            {an
              ? 'Jarvis darf einzelne Kontakte anlegen und ändern. Die Freigabe '
                + 'bleibt nach einem Neustart bestehen, bis du sie hier '
                + 'ausschaltest.'
              : 'Zum Einschalten fragt macOS nach Touch ID oder deinem '
                + 'Anmeldekennwort. Danach bleibt die Freigabe bestehen, auch '
                + 'nach einem Neustart.'}
          </p>
          <p style={{
            margin: '6px 0 0', font: 'var(--pjc-font-label)',
            color: 'var(--color-text-muted)',
          }}>
            Gilt für Anlegen und Ändern einzelner Kontakte. Löschen und
            Massenänderungen sind davon nicht erfasst.
          </p>
        </div>

        <button
          type="button"
          data-testid="contacts-schreibfreigabe-schalter"
          role="switch"
          aria-checked={an}
          aria-label="Kontakte dauerhaft schreiben"
          disabled={laeuft || !geladen}
          onClick={umschalten}
          className="pjc-focusable"
          style={{
            flexShrink: 0, display: 'inline-flex', alignItems: 'center',
            gap: '6px', padding: '6px 12px', borderRadius: '8px',
            cursor: laeuft ? 'progress' : 'pointer',
            font: 'var(--pjc-font-label)',
            border: '1px solid var(--color-border)',
            background: an ? 'var(--pjc-selection-bg)' : 'var(--color-surface)',
            color: an ? 'var(--pjc-selection-fg)' : 'var(--color-text)',
          }}
        >
          {laeuft && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
          {laeuft ? 'Warte auf Bestätigung…' : an ? 'An' : 'Aus'}
        </button>
      </div>

      {hinweis && (
        <p
          data-testid="contacts-schreibfreigabe-hinweis"
          style={{
            margin: '10px 0 0', font: 'var(--pjc-font-label)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {hinweis}
        </p>
      )}

      {/* Die ehrliche Grenze, an der Stelle, an der sie jemand liest.
          Nicht behauptet wird, die Freigabe sei gegen andere Programme
          gesichert — sie ist eine Datei in deinem Benutzerordner. */}
      <p style={{
        margin: '10px 0 0', font: 'var(--pjc-font-label)',
        color: 'var(--color-text-muted)',
      }}>
        Dieser Weg verlangt deine Bestätigung am System. Er schützt nicht
        dagegen, dass ein anderes Programm unter deinem Benutzerkonto die
        Freigabedatei selbst anlegt.
      </p>
    </div>
  );
}

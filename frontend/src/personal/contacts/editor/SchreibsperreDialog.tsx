// Warum Schreiben gerade gesperrt ist — und was der Eigentümer dagegen tut.
//
// Vor diesem Dialog war der Zustand stumm: Bei `channel_mode: disabled`
// verschwanden die Schreib-Einstiegspunkte, und die Oberfläche sah aus, als
// gäbe es sie nicht. Wer die Freigabe nicht ohnehin kannte, hatte keinen Weg
// zu ihr.
//
// **Was dieser Dialog ausdrücklich nicht tut: eine Freigabe erzeugen.** Die
// Erteilung ist eine Eigentümerhandlung (Dauerregeln §4, DEC-069). Jarvis darf
// den Weg zeigen; er darf ihn nicht gehen. Es gibt hier deshalb keinen Knopf,
// der schreibt — nur einen, der **erneut prüft**.

import { useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { AppChannelCapabilities, Capabilities } from '../api';
import { Modal } from '../components';
import { aktionsKnopf } from '../detail/ContactDetailPane';

/**
 * Der Grund, so genau wie er sicher bekannt ist — und nicht genauer.
 *
 * Die Rückgabe unterscheidet drei Lagen, weil sie zu drei verschiedenen
 * Handlungen führen. Sie zu einer „Schreiben geht nicht"-Meldung
 * zusammenzuziehen, hiesse dem Eigentümer die Handlung vorzuenthalten.
 */
export function sperrgrund(
  caps: Capabilities | null,
  kanal: AppChannelCapabilities | null,
): { titel: string; text: string; freigabeHilft: boolean } {
  if (kanal && !kanal.native_create_available) {
    return {
      titel: 'Dieser Stand kann nicht schreiben',
      text: 'Der native Schreibpfad ist in diesem Build nicht enthalten. Eine '
        + 'Freigabe würde daran nichts ändern.',
      freigabeHilft: false,
    };
  }
  if (caps && !caps.read_supported) {
    return {
      titel: 'Die Kontaktbrücke antwortet nicht',
      text: 'Ohne gelesenen Bestand gibt es kein Ziel für eine Änderung. '
        + 'Prüfe zuerst Verbindung und Berechtigung.',
      freigabeHilft: false,
    };
  }
  return {
    titel: 'Schreiben ist gesperrt',
    text: 'Der Schreibpfad ist vorhanden, aber es liegt keine gültige '
      + 'Schreibfreigabe vor. Freigaben laufen ab — höchstens vier Stunden — '
      + 'und gelten je Operation einzeln.',
    freigabeHilft: true,
  };
}

export function SchreibsperreDialog({ caps, kanal, offen, onClose, onErneutPruefen }: {
  caps: Capabilities | null;
  kanal: AppChannelCapabilities | null;
  offen: boolean;
  onClose: () => void;
  /** Lädt Fähigkeiten und Kanalauskunft neu. Erzeugt **nichts**. */
  onErneutPruefen: () => Promise<void>;
}) {
  const [prueft, setPrueft] = useState(false);
  const grund = sperrgrund(caps, kanal);

  return (
    <Modal
      open={offen}
      onClose={onClose}
      title={grund.titel}
      description={grund.text}
      footer={(
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose} className="pjc-focusable"
                  style={aktionsKnopf(false)}>
            Schliessen
          </button>
          <button
            type="button" data-testid="schreibsperre-erneut-pruefen"
            disabled={prueft}
            onClick={async () => {
              setPrueft(true);
              try { await onErneutPruefen(); } finally { setPrueft(false); }
            }}
            className="pjc-focusable pjc-primary"
            style={{
              ...aktionsKnopf(false),
              backgroundColor: 'var(--pjc-selection-bg)',
              color: 'var(--pjc-selection-fg)', border: 'none',
            }}>
            {prueft && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
            {' '}Erneut prüfen
          </button>
        </div>
      )}
    >
      <div data-testid="schreibsperre" style={{ font: 'var(--pjc-font-body)' }}>
        {grund.freigabeHilft && (
          <>
            <p style={{ margin: '0 0 8px' }}>
              Die Freigabe erteilst <strong>du</strong> — Jarvis kann und darf
              das nicht selbst. Sie ist eine Datei neben der Personal-Datenbank,
              die Vertrag, freigegebene Operationen und Ablauf nennt:
            </p>
            <p style={{
              margin: '0 0 8px', font: 'var(--pjc-font-label)',
              color: 'var(--color-text-muted)',
            }}>
              <code>contacts-write-release.json</code> · Vertrag{' '}
              <code>contacts-write-v1</code> · Rechte 0600 in einem
              0700-Verzeichnis
            </p>
            <p style={{ margin: '0 0 8px' }}>
              Sobald sie liegt, erkennt Jarvis sie ohne Neustart. „Erneut
              prüfen" liest den Stand neu.
            </p>
          </>
        )}
        <p style={{
          margin: 0, font: 'var(--pjc-font-label)',
          color: 'var(--color-text-muted)',
        }}>
          Lesen, Suchen und das Vorbereiten von Vorgängen bleiben in jedem Fall
          möglich. Gesperrt ist ausschliesslich die Übertragung an Apple
          Kontakte.
        </p>
      </div>
    </Modal>
  );
}

// Der Erteilungsweg der dauerhaften Kontakte-Schreibfreigabe — Frontendseite.
//
// Bewusst dünn: Es gibt hier keine Zustandslogik und keine Entscheidung. Der
// App-Prozess entscheidet, verlangt die Systemauthentisierung, schreibt die
// Urkunde und **liest sie mit demselben Leser gegen**, den der Schreibpfad
// benutzt. Was hier ankommt, ist ein gemessener Zustand, keine Absicht.
//
// Insbesondere gibt es keine HTTP-Route dafür. Läge der Schalter im Backend,
// könnte Jarvis ihn selbst betätigen.

import { isTauri } from '../../../lib/api';

/** Der gemessene Zustand der Dauerfreigabe. */
export interface StandingWriteState {
  /** Ob im Augenblick eine gültige Dauerfreigabe gilt. */
  standing: boolean;
  /** Die Operationen, die sie erteilt — heute höchstens `create` und `update`. */
  operations: string[];
  /** Geschlossene Kennung, warum ein Versuch scheiterte. */
  reason_code: string | null;
}

export const AUS: StandingWriteState = {
  standing: false, operations: [], reason_code: null,
};

/**
 * Der Grund in Lukas' Sprache — und ohne Dramatik.
 *
 * Ein Abbruch am Touch-ID-Dialog ist der häufigste Fall und ausdrücklich
 * kein Fehler: Er verdient einen Satz, keine Warnung.
 */
export function grundText(reason: string | null): string | null {
  switch (reason) {
    case null:
    case undefined:
      return null;
    case 'owner_authentication_failed':
      return 'Die Systemauthentifizierung wurde abgebrochen oder ist '
        + 'fehlgeschlagen. Schreiben bleibt aus.';
    case 'owner_authentication_unavailable':
      return 'Dieser Mac kann gerade keine Eigentümerauthentifizierung '
        + 'anfordern. Prüfe Touch ID und das Anmeldekennwort in den '
        + 'Systemeinstellungen.';
    case 'release_directory_not_private':
      return 'Der Ablageort der Freigabe hat nicht die erwarteten Rechte. '
        + 'Es wurde nichts geschrieben.';
    case 'write_failed':
      return 'Die Freigabe konnte nicht geschrieben werden.';
    case 'verification_failed':
      return 'Die geschriebene Freigabe wurde beim Gegenlesen nicht '
        + 'angenommen. Schreiben bleibt aus.';
    default:
      return 'Schreiben bleibt aus.';
  }
}

async function rufe(kommando: string): Promise<StandingWriteState> {
  if (!isTauri()) {
    // Im Browser gibt es keinen Prozess, dem macOS eine Authentisierung
    // zuordnen könnte. Ehrlich aus statt scheinbar an.
    return { ...AUS, reason_code: 'owner_authentication_unavailable' };
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<StandingWriteState>(kommando);
  } catch {
    return { ...AUS, reason_code: 'owner_authentication_unavailable' };
  }
}

/** Liest den Zustand. Ändert nichts und fragt nichts ab. */
export function leseZustand(): Promise<StandingWriteState> {
  return rufe('personal_contacts_standing_write_state');
}

/** Schaltet ein — löst die Systemauthentifizierung aus. */
export function schalteEin(): Promise<StandingWriteState> {
  return rufe('personal_contacts_standing_write_enable');
}

/** Schaltet aus. Verlangt ausdrücklich **keine** Authentifizierung. */
export function schalteAus(): Promise<StandingWriteState> {
  return rufe('personal_contacts_standing_write_disable');
}

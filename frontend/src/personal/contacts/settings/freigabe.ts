// Der Weg der Einzelfreigabe: erst der Beleg im App-Prozess, dann die Route.
//
// **Die Reihenfolge ist die Sicherheitsaussage.** Der Beleg entsteht aus der
// Handlung des Eigentümers auf der Fläche und bindet Vorgang, Nutzlast und
// Darstellung. Erst danach fragt der Kern; findet er keinen passenden Beleg,
// scheitert die Freigabe. Ein Aufruf der Route allein — das, was am
// 2026-08-17 gemessen 25 von 25 Mutationen durchliess — bewirkt nichts mehr.
//
// Diese Datei berechnet keine Digests. Sie reicht durch, was der Kern zu
// genau diesem Vorgang gespeichert hat. Würde sie rechnen, gäbe es zwei
// Wahrheiten über dieselbe Vorschau.

import { approveMutation, ContactsApiError } from '../api';
import { isTauri } from '../../../lib/api';

/** Warum eine Freigabe nicht zustande kam — geschlossene Kennungen. */
export type FreigabeFehler =
  | 'attestation_unavailable'
  | 'attestation_failed'
  | 'preview_changed'
  | 'approval_failed';

export class FreigabeAbgelehnt extends Error {
  constructor(readonly grund: FreigabeFehler, readonly technisch?: string) {
    super(grund);
    this.name = 'FreigabeAbgelehnt';
  }
}

/**
 * Der Satz, den Lukas liest.
 *
 * `preview_changed` ist der Fall, der im Alltag auftreten **wird**: Er gibt
 * frei, danach läuft ein Abgleich und füllt etwa den Containernamen, und der
 * Beleg passt nicht mehr. Der Abbruch ist gewollt — was er gesehen hat, gilt
 * nicht mehr. Ohne Erklärung hielte er das gewünschte Verhalten für einen
 * Defekt, und das ist der sicherste Weg, eine Sicherung wieder abzuschalten.
 */
export function fehlerText(grund: FreigabeFehler): string {
  switch (grund) {
    case 'preview_changed':
      return 'Die Vorschau hat sich seit deiner Freigabe geändert — sie zeigt '
        + 'jetzt etwas anderes als eben. Sieh sie dir bitte noch einmal an und '
        + 'gib sie erneut frei. Es wurde nichts übertragen.';
    case 'attestation_unavailable':
      return 'Freigeben geht nur in der Jarvis-App. Im Browser gibt es keinen '
        + 'Prozess, dem deine Handlung zugeordnet werden könnte.';
    case 'attestation_failed':
      return 'Deine Freigabe konnte nicht belegt werden. Es wurde nichts '
        + 'übertragen.';
    case 'approval_failed':
    default:
      return 'Die Freigabe wurde nicht angenommen. Es wurde nichts übertragen.';
  }
}

/**
 * Die Bindung, die ein Beleg braucht — und mehr nicht.
 *
 * Bewusst nicht `PreparedMutation`: Der Dialog haelt eine Vorschau, das Board
 * einen Vorgang, und beide tragen genau diese drei Angaben. Ein breiterer Typ
 * zwaenge eine der beiden Flaechen, sich etwas zu bauen, das sie nicht hat.
 */
export interface Freigabebindung {
  mutation_id: string;
  payload_digest: string;
  preview_digest: string;
}

async function belegen(vorgang: Freigabebindung): Promise<void> {
  if (!isTauri()) {
    throw new FreigabeAbgelehnt('attestation_unavailable');
  }
  let ergebnis: { written: boolean; reason_code: string | null };
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    ergebnis = await invoke('personal_contacts_attest_owner_approval', {
      mutationId: vorgang.mutation_id,
      // Durchgereicht, nicht gerechnet: beide Digests stammen aus genau dem
      // Datensatz, dessen Vorschau auf der Flaeche stand.
      payloadDigest: vorgang.payload_digest,
      previewDigest: vorgang.preview_digest,
    });
  } catch (e) {
    throw new FreigabeAbgelehnt('attestation_failed', String(e));
  }
  if (!ergebnis.written) {
    throw new FreigabeAbgelehnt('attestation_failed',
                                ergebnis.reason_code ?? undefined);
  }
}

/**
 * Belegt die Handlung und erteilt die Freigabe. Führt **nichts** aus.
 *
 * `actor` bleibt Protokoll für die Auditspur — er ist seit dem 17.08.
 * ausdrücklich kein Nachweis mehr.
 */
export async function freigeben(vorgang: Freigabebindung,
                                actor: string): Promise<void> {
  await belegen(vorgang);
  try {
    await approveMutation(vorgang.mutation_id, actor);
  } catch (e) {
    // Der Kern hat den Beleg nicht angenommen. Der haeufigste Grund ist eine
    // inzwischen veraenderte Vorschau — und genau das muss der Satz sagen.
    if (e instanceof ContactsApiError && e.code === 'owner_attestation_missing') {
      throw new FreigabeAbgelehnt('preview_changed', e.code);
    }
    throw new FreigabeAbgelehnt('approval_failed',
                                e instanceof Error ? e.message : String(e));
  }
}

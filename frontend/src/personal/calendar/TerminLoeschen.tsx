// Der Lösch-Dialog des Kalenders (B3 P3) — bewusst schmal, kein Redesign
// (Dialogoptik bleibt aufgeschoben, F1).
//
// Ablauf: beim Öffnen läuft die READ-ONLY Delete-Safety-Probe am nativen
// Event; nur ein nachweislich verlustfrei wiederherstellbarer Termin erreicht
// die Server-Vorbereitung. Die VORSCHAU ist ausschliesslich die vom SERVER
// gebaute — freigegeben wird, was man sieht — mit GENAU EINEM Freigabeknopf.
// Danach der Claim-Settle-Kanal wie bei Create/Update: approve → claim →
// App-Prozess (höchstens einmal) → settle. Kein Sync. Abbrechen mutiert nie.
// Normativ: DEC-069 — Kalenderschreiben produktiv zugelassen:
// einzelfreigegebene Mutationen über den getrennten Schreibpfad
// (docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md).

import { useEffect, useRef, useState } from 'react';
import './tokens.css';
import type { Termin } from './api';
import {
  type KalenderExecutionReport, type LoeschProbe, type VorbereiteterVorgang,
  MutationsFehler,
  beanspruche, bereiteLoeschenVor, bricheAb, erhebeLoeschProbe, fuehreAus,
  gibFrei, schliesseAb,
} from './mutationsApi';
import { lokalerTag, plusTage, uhrzeit } from './raster';

/** Deutsche Ansage je Eligibility-Flag — die geschlossene Menge des
 *  Vertrags (`ELIGIBILITY_FLAG_NAMES`), nie ein Inhalt. */
const FLAG_LABELS: Record<string, string> = {
  alarms: 'Wecker',
  attendees: 'Teilnehmer',
  availability_marked: 'Verfügbarkeitsmarkierung',
  birthday_link: 'Geburtstagsbindung',
  detached_occurrence: 'abgelöste Serieninstanz',
  organizer: 'Organisator/Einladung',
  participation_status: 'Teilnahmestatus',
  recurrence_rules: 'Wiederholungsregel',
  structured_location_geo: 'Ort mit Geokoordinate',
  url: 'URL',
};

/** Die Zeitzeile der Vorschau — aus den SERVER-Instants, lokal aufgelöst. */
function zeitZeile(p: { starts_at_utc: string; ends_at_utc: string;
                        is_all_day: boolean }, zone: string): string {
  if (p.is_all_day) {
    const start = lokalerTag(p.starts_at_utc, zone);
    const letzter = plusTage(lokalerTag(p.ends_at_utc, zone), -1);
    return start === letzter
      ? `Ganztägig · ${start}`
      : `Ganztägig · ${start} bis ${letzter}`;
  }
  return `${lokalerTag(p.starts_at_utc, zone)} · `
    + `${uhrzeit(p.starts_at_utc, zone)} – ${uhrzeit(p.ends_at_utc, zone)}`;
}

/** Vorbereitungs-/Freigabefehler → deutsche Ansage mit typisiertem Grund. */
function fehlerText(e: unknown): string {
  const grund = e instanceof MutationsFehler && e.reasonCode !== null
    ? e.reasonCode
    : e instanceof Error ? e.message : 'unbekannt';
  const ANSAGEN: Record<string, string> = {
    delete_not_eligible: 'Der Server hat die Löschung abgelehnt: der Termin '
      + 'trägt Eigenschaften, die Jarvis nicht verlustfrei wiederherstellen '
      + 'kann. Es wurde nichts gelöscht.',
    event_not_found: 'Der Termin ist im Bestand nicht (mehr) vorhanden — '
      + 'bitte aktualisieren.',
    backup_missing: 'Es liegt kein verifizierter Sicherungsnachweis vor — '
      + 'erst sichern, dann freigeben.',
    app_process_unavailable: 'Diese Ansicht läuft ausserhalb der Jarvis-App; '
      + 'nur die gepackte App darf löschen.',
    approval_consumed: 'Die Freigabe wurde bereits verbraucht — bitte den '
      + 'Vorgang neu vorbereiten und erneut freigeben.',
  };
  return ANSAGEN[grund]
    ?? `Der Löschfluss ist fehlgeschlagen (${grund}). Es wurde nichts `
      + 'gelöscht, solange kein Sendeversuch gemeldet wurde.';
}

type Schritt = 'lade' | 'blocked' | 'vorschau' | 'ergebnis';

export interface TerminLoeschenProps {
  termin: Termin;
  zone: string;
  aufSchliessen: () => void;
  /** Nur nach BELEGTEM Erfolg — der Workspace liest den Bestand dann neu. */
  aufErfolg: () => void;
}

export function TerminLoeschen({ termin, zone, aufSchliessen,
                                 aufErfolg }: TerminLoeschenProps) {
  const [schritt, setSchritt] = useState<Schritt>('lade');
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [flags, setFlags] = useState<string[]>([]);
  const [vorgang, setVorgang] = useState<VorbereiteterVorgang | null>(null);
  const [ergebnis, setErgebnis] = useState<{ ok: boolean; text: string } | null>(null);
  const gestartet = useRef(false);

  useEffect(() => {
    // Genau EIN Vorbereitungslauf je Dialog — auch unter StrictMode.
    if (gestartet.current) return;
    gestartet.current = true;
    void (async () => {
      try {
        // 1. Die Probe am NATIVEN Event — read-only, PII-arm. Jede
        //    Fehlstufe wird BENANNT gemeldet, nie stufenlos.
        const probeErgebnis = await erhebeLoeschProbe(termin.provider_event_id);
        if (probeErgebnis.stage !== 'ok') {
          const STUFEN: Record<string, string> = {
            not_authorized: 'Der App-Prozess hat keine Kalenderberechtigung '
              + '(TCC) — ohne sie gibt es keinen Löschweg.',
            event_unreadable: 'EventKit löst den Termin unter seiner Kennung '
              + 'im App-Prozess nicht auf — ohne frische Prüfung gibt es '
              + 'keinen Löschweg.',
            probe_unparseable: 'Die native Probe lieferte eine unlesbare '
              + 'Antwort — ohne frische Prüfung gibt es keinen Löschweg.',
            platform_unavailable: 'Diese Plattform hat keinen '
              + 'Kalenderzugriff.',
            channel_invalid: 'Der Probe-Kanal antwortete ausserhalb des '
              + 'Vertrags — ohne frische Prüfung gibt es keinen Löschweg.',
          };
          setFehler(`${STUFEN[probeErgebnis.stage] ?? probeErgebnis.stage} `
            + `(Stufe: ${probeErgebnis.stage})`);
          setSchritt('ergebnis');
          setErgebnis({ ok: false, text: 'Es wurde nichts gelöscht.' });
          return;
        }
        const probe: LoeschProbe = probeErgebnis.probe;
        if (!probe.eligible) {
          // Sichtbar verweigern statt warnen-und-löschen. Nichts wurde
          // vorbereitet, nichts erreicht den Server.
          setFlags(probe.unsupported_feature_flags);
          setSchritt('blocked');
          return;
        }
        // 2. Die Server-Vorbereitung bindet Fingerprint, Eligibility-Digest
        //    und Restore-Artefakt in die Freigabe.
        const v = await bereiteLoeschenVor(
          termin.provider_calendar_id, termin.provider_event_id, probe);
        setVorgang(v);
        setSchritt('vorschau');
      } catch (e) {
        setFehler(fehlerText(e));
        setSchritt('ergebnis');
        setErgebnis({ ok: false, text: 'Es wurde nichts gelöscht.' });
      }
    })();
  }, [termin]);

  const abbrechen = async () => {
    if (vorgang !== null && schritt === 'vorschau') {
      setLaeuft(true);
      try {
        await bricheAb(vorgang.mutation_id);
      } catch {
        // Der Abbruch selbst schlug fehl — der Vorgang verfällt serverseitig
        // über die Freigabe-TTL. Gesendet wurde weiterhin nichts.
      } finally {
        setLaeuft(false);
      }
    }
    aufSchliessen();
  };

  const loeschen = async () => {
    if (vorgang === null) return;
    const id = vorgang.mutation_id;
    setLaeuft(true);
    setFehler(null);
    try {
      await gibFrei(id);
      const auftrag = await beanspruche(id);

      let bericht: KalenderExecutionReport;
      try {
        // Der Auftrag geht UNVERÄNDERT hinüber — und höchstens einmal.
        bericht = await fuehreAus(JSON.stringify(auftrag));
      } catch (e) {
        const code = e instanceof Error ? e.message : 'unbekannt';
        setErgebnis({
          ok: false,
          text: `Der App-Prozess hat nicht geantwortet (${code}) — der `
            + 'Ausgang ist ungewiss. Es wurde kein zweiter Versuch unternommen.',
        });
        setSchritt('ergebnis');
        return;
      }

      const settle = await schliesseAb(id, auftrag.claim_token, bericht);
      if (settle.state === 'succeeded') {
        setErgebnis({ ok: true, text: 'Termin gelöscht — die Abwesenheit '
          + 'wurde über den gezielten Read-back bestätigt.' });
        aufErfolg();
      } else if (settle.state === 'provider_applied_pending_reconcile') {
        setErgebnis({
          ok: true,
          text: 'Löschung beim Provider ausgeführt — der lokale Bestand '
            + 'wird beim nächsten Abgleich nachgeführt.',
        });
      } else {
        const klasse = settle.error_class ?? bericht.error_class ?? 'unbekannt';
        const ANSAGEN: Record<string, string> = {
          revision_conflict: 'Nicht gelöscht — der Termin ist nicht mehr in '
            + 'dem Zustand, der freigegeben wurde. Es wurde nichts gesendet; '
            + 'die Freigabe ist verfallen. Bitte aktualisieren und neu prüfen.',
          unsupported_field: 'Nicht gelöscht — der Termin trägt inzwischen '
            + 'Eigenschaften, die Jarvis nicht verlustfrei wiederherstellen '
            + 'kann. Es wurde nichts gesendet.',
        };
        setErgebnis({
          ok: false,
          text: settle.state === 'failed_before_send'
            ? ANSAGEN[klasse]
              ?? `Nicht gelöscht (${klasse}) — es wurde nichts gesendet.`
            : `Ausgang ungewiss (${klasse}) — bitte den Kalender prüfen, `
              + 'bevor irgendetwas wiederholt wird.',
        });
      }
      setSchritt('ergebnis');
    } catch (e) {
      setErgebnis({ ok: false, text: fehlerText(e) });
      setSchritt('ergebnis');
    } finally {
      setLaeuft(false);
    }
  };

  const p = vorgang?.preview ?? null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="termin-loeschen-overlay"
      style={{ background: 'rgba(0, 0, 0, 0.35)' }}>
      <div role="dialog" aria-modal="true" aria-label="Termin löschen"
        className="rounded p-4 flex flex-col gap-3 overflow-y-auto"
        style={{ background: 'var(--pjk-surface)', color: 'var(--pjk-ink)',
                 border: '1px solid var(--pjk-line)',
                 width: 380, maxWidth: '92%', maxHeight: '85%' }}>
        <h2 className="text-sm font-semibold">Termin löschen</h2>

        {schritt === 'lade' && (
          <p className="text-[11px]" style={{ color: 'var(--pjk-ink-dim)' }}>
            Prüfe den Termin nativ und bereite die Löschung vor …
          </p>
        )}

        {schritt === 'blocked' && (
          <div data-testid="loeschen-blocked" className="flex flex-col gap-2">
            <p role="alert" className="text-xs"
              style={{ color: 'var(--color-error)' }}>
              Dieser Termin wird nicht gelöscht: er trägt Eigenschaften, die
              Jarvis nicht verlustfrei wiederherstellen kann.
            </p>
            <ul className="text-[11px] list-disc pl-4"
              style={{ color: 'var(--pjk-ink-dim)' }}>
              {flags.map((flag) => (
                <li key={flag}>{FLAG_LABELS[flag] ?? flag}</li>
              ))}
            </ul>
            <div className="flex justify-end pt-1">
              <button type="button" onClick={aufSchliessen}
                className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)' }}>
                Schließen
              </button>
            </div>
          </div>
        )}

        {schritt === 'vorschau' && p !== null && (
          <div data-testid="loeschen-vorschau" className="flex flex-col gap-2">
            {/* Ausschliesslich die SERVER-Vorschau: freigegeben wird, was
                man sieht. */}
            <p className="text-[11px]" style={{ color: 'var(--color-error)' }}>
              Dieser Termin wird beim Provider endgültig gelöscht.
            </p>
            <dl className="text-[11px] space-y-1">
              <div>
                <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                  Kalender
                </dt>
                <dd>{p.calendar_display_name}</dd>
              </div>
              <div>
                <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                  Titel
                </dt>
                <dd>{p.title ?? 'Ohne Titel'}</dd>
              </div>
              <div>
                <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                  Zeit
                </dt>
                <dd>{zeitZeile(p, zone)}</dd>
              </div>
              {p.location !== null && (
                <div>
                  <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                    Ort
                  </dt>
                  <dd>{p.location}</dd>
                </div>
              )}
            </dl>
            {p.deletion !== undefined && (
              <p data-testid="loeschen-eligibility" className="text-[10px]"
                style={{ color: 'var(--pjk-ink-dim)' }}>
                Nativ geprüft: verlustfrei wiederherstellbar
                {p.deletion.restore_preimage_present
                  ? ' · Wiederherstellungs-Vorlage liegt bereit.' : '.'}
              </p>
            )}

            {fehler !== null && (
              <p role="alert" className="text-[11px]"
                style={{ color: 'var(--color-error)' }}>{fehler}</p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => void abbrechen()}
                disabled={laeuft} className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)' }}>
                Abbrechen
              </button>
              {/* GENAU EIN Freigabeknopf. */}
              <button type="button" onClick={() => void loeschen()}
                disabled={laeuft} className="text-xs px-2 py-1 rounded font-semibold"
                style={{ background: 'var(--color-error)', color: '#fff',
                         opacity: laeuft ? 0.5 : 1 }}>
                {laeuft ? 'Läuft …' : 'Löschen freigeben'}
              </button>
            </div>
          </div>
        )}

        {schritt === 'ergebnis' && ergebnis !== null && (
          <div data-testid="loeschen-ergebnis" className="flex flex-col gap-2">
            <p role="status" className="text-xs"
              style={{ color: ergebnis.ok ? 'var(--pjk-ink)' : 'var(--color-error)' }}>
              {ergebnis.text}
            </p>
            {fehler !== null && (
              <p className="text-[11px]" style={{ color: 'var(--color-error)' }}>
                {fehler}
              </p>
            )}
            <div className="flex justify-end pt-1">
              <button type="button" onClick={aufSchliessen}
                className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)' }}>
                Schließen
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default TerminLoeschen;

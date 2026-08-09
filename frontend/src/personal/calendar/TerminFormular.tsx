// Die minimale Terminmaske des Kalenders (B3 P1: create · P2: update) —
// zwei Schritte.
//
// ENTWURF: die sieben Vertragsfelder, sonst nichts. VORSCHAU: ausschliesslich
// die vom SERVER gelieferte Vorschau — freigegeben wird, was man sieht — mit
// GENAU EINEM Freigabeknopf. Nichts ist vorangekreuzt, nichts läuft von
// selbst: normativ DEC-069 — Kalenderschreiben produktiv zugelassen:
// einzelfreigegebene Mutationen über den getrennten Schreibpfad
// (docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md).
//
// UPDATE-Modus (B3 P2, Delta-Semantik): die Maske wird aus dem Termin
// vorbelegt; beim Absenden reisen AUSSCHLIESSLICH die geänderten Felder als
// `changes`. Die Vorschau zeigt je Feld alt → neu; der eine Freigabeknopf
// heisst „Änderung freigeben". Die Startverschiebung nutzt denselben
// Dauererhalt wie der Create.
//
// Der Ablauf nach der Freigabe ist der Claim-Settle-Kanal des Kontaktmoduls:
// approve → claim → App-Prozess (höchstens einmal) → settle. Kein Sync.

import { useMemo, useState } from 'react';
import './tokens.css';
import type { KalenderZeile, Termin } from './api';
import {
  type KalenderExecutionReport, type TerminAenderungen, type TerminFelder,
  type VorbereiteterVorgang,
  MutationsFehler,
  beanspruche, bereiteUpdateVor, bereiteVor, bricheAb, fuehreAus, gibFrei,
  schliesseAb,
} from './mutationsApi';
import {
  lokaleMitternachtUtc, lokalerTag, plusTage, systemZeitzone, uhrzeit,
} from './raster';

/** ISO-8601 UTC in Sekundenpräzision — exakt das Vertragsformat des Servers
 *  (`YYYY-MM-DDTHH:MM:SSZ`, ohne Millisekunden). */
function utcSekunden(ms: number): string {
  return `${new Date(ms).toISOString().slice(0, 19)}Z`;
}

/**
 * Der UTC-Instant einer lokalen Uhrzeit an einem lokalen Kalendertag.
 *
 * Basis ist die lokale Mitternacht aus `raster.ts`; die eine Korrektur
 * danach fängt den Fall, dass zwischen Mitternacht und Zielzeit ein
 * DST-Sprung liegt — sonst wäre der Termin um eine Stunde verschoben.
 */
function lokaleUhrzeitUtc(tag: string, zeit: string, zone: string): string {
  const [h, m] = zeit.split(':').map(Number);
  const ziel = (h ?? 0) * 60 + (m ?? 0);
  const inst = Date.parse(lokaleMitternachtUtc(tag, zone)) + ziel * 60_000;
  const lokal = new Date(inst).toLocaleString('en-GB', {
    timeZone: zone, hour12: false, hour: '2-digit', minute: '2-digit',
  });
  const [lh, lm] = lokal.split(':').map(Number);
  let delta = (lh ?? 0) * 60 + (lm ?? 0) - ziel;
  // Mitternachtsnahe Zeiten: der Versatz wird modulo Tag interpretiert.
  if (delta > 720) delta -= 1440;
  if (delta < -720) delta += 1440;
  return utcSekunden(inst - delta * 60_000);
}

/** Statusklasse → deutsche Ansage. Kein Servertext wird durchgereicht. */
function vorbereitungsFehler(e: unknown): string {
  const code = e instanceof Error ? e.message : '';
  if (code === 'calendar_api_400') {
    return 'Der Server hat die Felder abgewiesen — Eingaben prüfen.';
  }
  if (code === 'calendar_api_404') {
    return 'Der Zielkalender ist im Bestand nicht (mehr) vorhanden.';
  }
  if (code === 'calendar_api_409') {
    return 'Der Vorgang ist im aktuellen Zustand nicht zulässig '
      + '(z. B. Kalender nicht beschreibbar oder Backup-Nachweis fehlt).';
  }
  return `Die Vorbereitung ist fehlgeschlagen (${code || 'unbekannt'}).`;
}

/** Freigabefehler → deutsche Ansage mit dem typisierten Servergrund und
 * dem nächsten Schritt. Ein Abbruch ohne Grund ist ein Diagnosemangel
 * (B3-Livebefund vom 2026-08-09). */
function freigabeFehler(e: unknown): string {
  const grund = e instanceof MutationsFehler && e.reasonCode !== null
    ? e.reasonCode
    : e instanceof Error ? e.message : 'unbekannt';
  const ANSAGEN: Record<string, string> = {
    schema_mismatch: 'Server und App-Prozess sprachen nicht denselben '
      + 'Auftragsvertrag — es wurde nichts angelegt. Bitte neu vorbereiten; '
      + 'besteht der Fehler fort, ist der Baustand der App veraltet.',
    approval_consumed: 'Die Freigabe wurde bereits verbraucht — bitte den '
      + 'Vorgang neu vorbereiten und erneut freigeben.',
    backup_missing: 'Es liegt kein verifizierter Sicherungsnachweis vor — '
      + 'erst sichern, dann freigeben.',
    app_process_unavailable: 'Diese Ansicht läuft ausserhalb der Jarvis-App; '
      + 'nur die gepackte App darf ausführen.',
  };
  const ansage = ANSAGEN[grund]
    ?? `Der Freigabefluss ist fehlgeschlagen (${grund}). Es wurde nichts `
      + 'angelegt; bitte neu vorbereiten.';
  return ansage;
}

/** Die Zeitzeile der Vorschau — aus den SERVER-Instants, lokal aufgelöst. */
function zeitZeile(p: { starts_at_utc: string; ends_at_utc: string;
                        is_all_day: boolean }, zone: string): string {
  if (p.is_all_day) {
    const start = lokalerTag(p.starts_at_utc, zone);
    // Exklusives Ende → letzter Tag ist der Vortag des End-Instants.
    const letzter = plusTage(lokalerTag(p.ends_at_utc, zone), -1);
    return start === letzter
      ? `Ganztägig · ${start}`
      : `Ganztägig · ${start} bis ${letzter}`;
  }
  return `${lokalerTag(p.starts_at_utc, zone)} · `
    + `${uhrzeit(p.starts_at_utc, zone)} – ${uhrzeit(p.ends_at_utc, zone)}`;
}

type Schritt = 'entwurf' | 'vorschau' | 'ergebnis';

interface Ergebnis {
  ok: boolean;
  text: string;
}

/** Die sieben Vertragsfelder — die Diff-Grundlage des Update-Modus. */
const VERTRAGSFELDER: readonly (keyof TerminFelder)[] = [
  'title', 'starts_at_utc', 'ends_at_utc', 'is_all_day', 'location', 'notes',
  'time_zone',
];

const FELD_LABELS: Record<string, string> = {
  title: 'Titel', starts_at_utc: 'Beginn', ends_at_utc: 'Ende',
  is_all_day: 'Ganztägig', location: 'Ort', notes: 'Notiz',
  time_zone: 'Zeitzone',
};

/** Anzeigewert eines Delta-Feldes — Zeiten lokal aufgelöst, `null` ehrlich. */
function wertText(feld: string, wert: unknown, zone: string): string {
  if (wert === null || wert === undefined) return '—';
  if (typeof wert === 'boolean') return wert ? 'ja' : 'nein';
  if ((feld === 'starts_at_utc' || feld === 'ends_at_utc')
      && typeof wert === 'string') {
    return `${lokalerTag(wert, zone)} ${uhrzeit(wert, zone)}`;
  }
  return String(wert);
}

const FELD_STIL = {
  border: '1px solid var(--pjk-line)',
  background: 'var(--pjk-surface-2)',
  color: 'var(--pjk-ink)',
} as const;

export interface TerminFormularProps {
  kalender: KalenderZeile[];
  zone: string;
  /** Vorbelegter lokaler Tag (gewählter Tag oder heute). */
  vorbelegterTag: string;
  /** B3 P2: liegt hier ein Termin, arbeitet die Maske im UPDATE-Modus —
   *  Vorbelegung aus dem Termin, beim Absenden NUR die geänderten Felder. */
  bearbeite?: Termin | null;
  aufSchliessen: () => void;
  /** Nur nach BELEGTEM Erfolg — der Workspace liest den Bestand dann neu. */
  aufErfolg: () => void;
}

export function TerminFormular({ kalender, zone, vorbelegterTag, bearbeite,
                                 aufSchliessen, aufErfolg }: TerminFormularProps) {
  // Nur beschreibbare Kalender sind wählbar — Provider-Wahrheit, die
  // Oberfläche überstimmt sie nie (P-6).
  const beschreibbar = useMemo(
    () => kalender.filter((k) => k.is_writable), [kalender]);
  const update = bearbeite ?? null;

  const [schritt, setSchritt] = useState<Schritt>('entwurf');
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const [titel, setTitel] = useState(update?.title ?? '');
  const [kalenderId, setKalenderId] = useState(
    update !== null ? update.provider_calendar_id
                    : beschreibbar[0]?.provider_calendar_id ?? '');
  const [datumStart, setDatumStart] = useState(
    () => update !== null
      ? lokalerTag(update.starts_at_utc, zone) : vorbelegterTag);
  const [zeitStart, setZeitStart] = useState(
    () => update !== null && !update.is_all_day
      ? uhrzeit(update.starts_at_utc, zone) : '09:00');
  const [datumEnde, setDatumEnde] = useState(
    () => update === null ? vorbelegterTag
      // Exklusives Ende: der letzte Tag eines Ganztagstermins ist der
      // Vortag des End-Instants — wie in der Vorschau-Zeitzeile.
      : update.is_all_day ? plusTage(lokalerTag(update.ends_at_utc, zone), -1)
        : lokalerTag(update.ends_at_utc, zone));
  const [zeitEnde, setZeitEnde] = useState(
    () => update !== null && !update.is_all_day
      ? uhrzeit(update.ends_at_utc, zone) : '10:00');
  const [ganztaegig, setGanztaegig] = useState(update?.is_all_day ?? false);
  const [ort, setOrt] = useState(update?.location ?? '');
  const [notiz, setNotiz] = useState(update?.notes ?? '');

  const [vorgang, setVorgang] = useState<VorbereiteterVorgang | null>(null);
  const [ergebnis, setErgebnis] = useState<Ergebnis | null>(null);

  /**
   * Dauererhalt: ein neuer Beginn schiebt das Ende automatisch um die
   * BISHERIGE Dauer mit — Enddatum UND Endzeit, über Mitternacht hinweg.
   * Direkte Ende-Änderungen (setDatumEnde/setZeitEnde an den Feldern)
   * bleiben bewusst unangetastet: keine Rückstellung auf die alte Dauer.
   */
  const setzeBeginn = (neuesDatum: string, neueZeit: string) => {
    if (ganztaegig) {
      // Ganztägig zählt in Kalendertagen: die Tagesdifferenz bleibt erhalten.
      const diffTage = Math.round(
        (Date.parse(`${datumEnde}T00:00:00Z`)
          - Date.parse(`${datumStart}T00:00:00Z`)) / 86_400_000);
      setDatumStart(neuesDatum);
      setZeitStart(neueZeit);
      if (Number.isFinite(diffTage)) setDatumEnde(plusTage(neuesDatum, diffTage));
      return;
    }
    // Dauer aus den AKTUELLEN vier Feldern — als Instants in der Prop-Zone,
    // damit DST-Tage nicht eine erfundene Stunde einschleppen.
    const dauerMs = Date.parse(lokaleUhrzeitUtc(datumEnde, zeitEnde, zone))
      - Date.parse(lokaleUhrzeitUtc(datumStart, zeitStart, zone));
    setDatumStart(neuesDatum);
    setZeitStart(neueZeit);
    const beginn = Date.parse(lokaleUhrzeitUtc(neuesDatum, neueZeit, zone));
    if (!Number.isFinite(dauerMs) || !Number.isFinite(beginn)) return;
    const ende = new Date(beginn + dauerMs).toISOString();
    setDatumEnde(lokalerTag(ende, zone));
    setZeitEnde(uhrzeit(ende, zone));
  };

  const zurVorschau = async () => {
    setFehler(null);
    if (kalenderId === '') {
      setFehler('Kein beschreibbarer Kalender vorhanden.');
      return;
    }
    // Ganztägig: lokale Mitternachts-Instants des gewählten Tags und des
    // FOLGETAGS des Endtags — das Ende ist exklusiv, wie im Bestand.
    const starts = ganztaegig
      ? utcSekunden(Date.parse(lokaleMitternachtUtc(datumStart, zone)))
      : lokaleUhrzeitUtc(datumStart, zeitStart, zone);
    const ends = ganztaegig
      ? utcSekunden(Date.parse(lokaleMitternachtUtc(plusTage(datumEnde, 1), zone)))
      : lokaleUhrzeitUtc(datumEnde, zeitEnde, zone);
    if (ends <= starts) {
      setFehler('Das Ende muss nach dem Beginn liegen.');
      return;
    }
    const kandidat: TerminFelder = {
      title: titel.trim() === '' ? null : titel.trim(),
      starts_at_utc: starts,
      ends_at_utc: ends,
      is_all_day: ganztaegig,
      location: ort.trim() === '' ? null : ort.trim(),
      notes: notiz.trim() === '' ? null : notiz.trim(),
      // Der Zeitzonenanker: beim CREATE mechanisch aus der Plattformquelle
      // (`systemZeitzone()`), nie hart codiert; ganztägig sendet `null`
      // (der Bestand trägt Ganztagstermine schwebend, m0009). Beim UPDATE
      // bleibt der Anker DES TERMINS unangetastet — eine Zeitverschiebung
      // ändert Instants, nie die Zone, und Floating bleibt Floating.
      time_zone: ganztaegig ? null
        : update !== null ? update.time_zone : systemZeitzone(),
    };
    setLaeuft(true);
    try {
      let v: VorbereiteterVorgang;
      if (update !== null) {
        // DELTA, kein Full Replace: nur die tatsächlich geänderten Felder
        // reisen. Nicht-ändern heisst weglassen — nie null senden.
        const aenderungen: TerminAenderungen = {};
        for (const feld of VERTRAGSFELDER) {
          if (kandidat[feld] !== update[feld]) {
            (aenderungen as Record<string, unknown>)[feld] = kandidat[feld];
          }
        }
        if (Object.keys(aenderungen).length === 0) {
          setFehler('Keine Änderung erkannt — es gibt nichts freizugeben.');
          setLaeuft(false);
          return;
        }
        v = await bereiteUpdateVor(update.provider_calendar_id,
                                   update.provider_event_id, aenderungen);
      } else {
        v = await bereiteVor(kalenderId, kandidat);
      }
      setVorgang(v);
      setSchritt('vorschau');
    } catch (e) {
      setFehler(vorbereitungsFehler(e));
    } finally {
      setLaeuft(false);
    }
  };

  const abbrechen = async () => {
    // In der Vorschau existiert bereits ein vorbereiteter Vorgang — der
    // wird serverseitig beendet. Gesendet wurde in keinem Fall etwas.
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

  const anlegen = async () => {
    if (vorgang === null) return;
    const id = vorgang.mutation_id;
    setLaeuft(true);
    setFehler(null);
    try {
      await gibFrei(id);
      const auftrag = await beanspruche(id);

      let bericht: KalenderExecutionReport;
      try {
        // Der Auftrag geht UNVERÄNDERT hinüber — und höchstens einmal:
        // schlägt der Aufruf fehl, weiss niemand, ob gesendet wurde.
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
        // Nach dem Settle ist die Termintabelle serverseitig nachgeführt —
        // ein einfaches Neuladen des Bestands genügt.
        setErgebnis({ ok: true, text: update !== null
          ? 'Termin aktualisiert.' : 'Termin angelegt.' });
        aufErfolg();
      } else if (settle.state === 'provider_applied_pending_reconcile') {
        setErgebnis({
          ok: true,
          text: (update !== null
            ? 'Änderung beim Provider gespeichert'
            : 'Termin beim Provider angelegt')
            + ' — der lokale Bestand wird beim nächsten Abgleich nachgeführt.',
        });
      } else {
        const klasse = settle.error_class ?? bericht.error_class ?? 'unbekannt';
        setErgebnis({
          ok: false,
          text: settle.state === 'failed_before_send'
            ? klasse === 'revision_conflict'
              ? 'Nicht geändert — der Termin wurde zwischenzeitlich '
                + 'anderweitig geändert. Es wurde nichts gesendet; bitte '
                + 'aktualisieren und erneut bearbeiten.'
              : `Nicht ${update !== null ? 'geändert' : 'angelegt'} `
                + `(${klasse}) — es wurde nichts gesendet.`
            : `Ausgang ungewiss (${klasse}) — bitte den Kalender prüfen.`,
        });
      }
      setSchritt('ergebnis');
    } catch (e) {
      setErgebnis({ ok: false, text: freigabeFehler(e) });
      setSchritt('ergebnis');
    } finally {
      setLaeuft(false);
    }
  };

  const p = vorgang?.preview ?? null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="termin-formular-overlay"
      style={{ background: 'rgba(0, 0, 0, 0.35)' }}>
      <div role="dialog" aria-modal="true"
        aria-label={update !== null ? 'Termin bearbeiten' : 'Neuer Termin'}
        className="rounded p-4 flex flex-col gap-3 overflow-y-auto"
        style={{ background: 'var(--pjk-surface)', color: 'var(--pjk-ink)',
                 border: '1px solid var(--pjk-line)',
                 width: 380, maxWidth: '92%', maxHeight: '85%' }}>
        <h2 className="text-sm font-semibold">
          {update !== null ? 'Termin bearbeiten' : 'Neuer Termin'}
        </h2>

        {schritt === 'entwurf' && (
          <form data-testid="termin-entwurf" className="flex flex-col gap-2"
            onSubmit={(e) => { e.preventDefault(); void zurVorschau(); }}>
            <label className="text-[11px] flex flex-col gap-1">
              Titel
              <input type="text" value={titel} aria-label="Titel"
                onChange={(e) => setTitel(e.target.value)}
                className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
            </label>

            {update !== null ? (
              // Das Ziel eines Updates steht fest: DERSELBE Termin in
              // DEMSELBEN Kalender — ein Kalenderwechsel ist kein Update.
              <p className="text-[11px]" style={{ color: 'var(--pjk-ink-dim)' }}>
                Kalender: {update.calendar_name}
              </p>
            ) : (
              <label className="text-[11px] flex flex-col gap-1">
                Kalender
                <select value={kalenderId} aria-label="Kalender"
                  onChange={(e) => setKalenderId(e.target.value)}
                  className="text-xs px-2 py-1 rounded" style={FELD_STIL}>
                  {beschreibbar.map((k) => (
                    <option key={k.id} value={k.provider_calendar_id}>
                      {k.display_name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {update === null && beschreibbar.length === 0 && (
              <p className="text-[11px]" style={{ color: 'var(--color-error)' }}>
                Kein Kalender ist laut Provider beschreibbar.
              </p>
            )}

            <label className="text-[11px] flex items-center gap-2">
              <input type="checkbox" checked={ganztaegig}
                aria-label="Ganztägig"
                onChange={(e) => setGanztaegig(e.target.checked)} />
              Ganztägig
            </label>

            <div className="flex gap-2">
              <label className="text-[11px] flex flex-col gap-1 flex-1">
                Datum Beginn
                <input type="date" value={datumStart} aria-label="Datum Beginn"
                  onChange={(e) => setzeBeginn(e.target.value, zeitStart)}
                  className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
              </label>
              {!ganztaegig && (
                <label className="text-[11px] flex flex-col gap-1">
                  Uhrzeit Beginn
                  <input type="time" value={zeitStart} aria-label="Uhrzeit Beginn"
                    onChange={(e) => setzeBeginn(datumStart, e.target.value)}
                    className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
                </label>
              )}
            </div>

            <div className="flex gap-2">
              <label className="text-[11px] flex flex-col gap-1 flex-1">
                Datum Ende
                <input type="date" value={datumEnde} aria-label="Datum Ende"
                  onChange={(e) => setDatumEnde(e.target.value)}
                  className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
              </label>
              {!ganztaegig && (
                <label className="text-[11px] flex flex-col gap-1">
                  Uhrzeit Ende
                  <input type="time" value={zeitEnde} aria-label="Uhrzeit Ende"
                    onChange={(e) => setZeitEnde(e.target.value)}
                    className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
                </label>
              )}
            </div>

            <label className="text-[11px] flex flex-col gap-1">
              Ort
              <input type="text" value={ort} aria-label="Ort"
                onChange={(e) => setOrt(e.target.value)}
                className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
            </label>

            <label className="text-[11px] flex flex-col gap-1">
              Notiz
              <textarea value={notiz} aria-label="Notiz" rows={3}
                onChange={(e) => setNotiz(e.target.value)}
                className="text-xs px-2 py-1 rounded" style={FELD_STIL} />
            </label>

            {fehler !== null && (
              <p role="alert" data-testid="termin-fehler" className="text-[11px]"
                style={{ color: 'var(--color-error)' }}>{fehler}</p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => void abbrechen()}
                disabled={laeuft} className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)' }}>
                Abbrechen
              </button>
              <button type="submit"
                disabled={laeuft || (update === null && beschreibbar.length === 0)}
                className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)',
                         opacity: laeuft
                           || (update === null && beschreibbar.length === 0)
                           ? 0.5 : 1 }}>
                {laeuft ? 'Läuft …' : 'Weiter zur Vorschau'}
              </button>
            </div>
          </form>
        )}

        {schritt === 'vorschau' && p !== null && (
          <div data-testid="termin-vorschau" className="flex flex-col gap-2">
            {/* Ausschliesslich die SERVER-Vorschau: freigegeben wird, was
                man sieht — nicht, was das Formular glaubt gesendet zu haben. */}
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
              <div>
                <dt className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                  Zeitzone
                </dt>
                {/* Die SERVER-validierte Zone — freigegeben wird auch der
                    Anker, nicht nur die Uhrzeit. */}
                <dd>{p.time_zone ?? 'schwebend — ohne feste Zeitzone'}</dd>
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

            {/* UPDATE: das SERVER-gebaute Delta — je Feld alt → neu.
                Freigegeben wird genau diese Änderung, nichts anderes. */}
            {p.command === 'update' && p.changes !== undefined && (
              <div data-testid="termin-aenderungen" className="text-[11px]">
                <p className="font-medium" style={{ color: 'var(--pjk-ink-dim)' }}>
                  Änderungen
                </p>
                <ul className="space-y-1">
                  {Object.entries(p.changes).map(([feld, delta]) => (
                    <li key={feld}>
                      {FELD_LABELS[feld] ?? feld}:{' '}
                      <span style={{ color: 'var(--pjk-ink-dim)' }}>
                        {wertText(feld, delta.from, zone)}
                      </span>
                      {' → '}
                      <span className="font-medium">
                        {wertText(feld, delta.to, zone)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {fehler !== null && (
              <p role="alert" data-testid="termin-fehler" className="text-[11px]"
                style={{ color: 'var(--color-error)' }}>{fehler}</p>
            )}

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={() => void abbrechen()}
                disabled={laeuft} className="text-xs px-2 py-1 rounded"
                style={{ border: '1px solid var(--pjk-line)' }}>
                Abbrechen
              </button>
              {/* GENAU EIN Freigabeknopf. */}
              <button type="button" onClick={() => void anlegen()}
                disabled={laeuft} className="text-xs px-2 py-1 rounded font-semibold"
                style={{ background: 'var(--pjk-auswahl)',
                         color: 'var(--pjk-auswahl-text)',
                         opacity: laeuft ? 0.5 : 1 }}>
                {laeuft ? 'Läuft …'
                  : update !== null ? 'Änderung freigeben' : 'Anlegen'}
              </button>
            </div>
          </div>
        )}

        {schritt === 'ergebnis' && ergebnis !== null && (
          <div data-testid="termin-ergebnis" className="flex flex-col gap-2">
            <p role="status" className="text-xs"
              style={{ color: ergebnis.ok ? 'var(--pjk-ink)' : 'var(--color-error)' }}>
              {ergebnis.text}
            </p>
            {ergebnis.ok && (
              <p className="text-[10px]" style={{ color: 'var(--pjk-ink-dim)' }}>
                Die Ansicht liest den gespeicherten Bestand neu.
                „Aktualisieren" führt zusätzlich den Provider-Sync aus.
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

export default TerminFormular;

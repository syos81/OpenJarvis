// Dreispaltiger Kalender-Workspace: Kalenderliste · Raster · Detail.
//
// Dieser Baustein besitzt den Datenzustand, die Auswahl, den Ansichtsmodus und
// den Anker. Die Flächen in `panes.tsx` sind reine Präsentation.
//
// Verbindlich:
//  · KEIN Auto-Sync. Der Mount und jeder Ansichtswechsel LESEN nur den
//    gespeicherten Bestand. Synchronisiert wird ausschliesslich auf Klick.
//  · Kein Timer, kein Poller, kein Intervall.
//  · Betrieb: lesend PLUS einzelfreigegebene Mutationen — normativ DEC-069 —
//    Kalenderschreiben produktiv zugelassen: einzelfreigegebene Mutationen
//    über den getrennten Schreibpfad
//    (docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md).
//    Geschrieben wird ausschliesslich über das Terminformular mit
//    ausdrücklicher Einzelfreigabe; nichts schreibt von selbst.
//  · Die Oberfläche zeigt, welchen Zeitraum sie kennt. Ein Kalender, der so
//    tut, als kenne er alles, lügt.
//  · Sichtbarkeitsfilter sind reine Anzeige und werden nirgends gespeichert.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './tokens.css';
import {
  type KalenderZeile, type LaufBericht, type ModulStatus, type Termin,
  frageBerechtigungAn, ladeKalender, ladeStatus, ladeTermine, pruefeBridge,
  synchronisiere,
} from './api';
import {
  CalendarSidebar, JahresRaster, MonatsRaster, TagesListe, TerminDetail,
  ZeitRaster,
} from './panes';
import { TerminFormular } from './TerminFormular';
import { TerminLoeschen } from './TerminLoeschen';
import { PanelLeft } from 'lucide-react';
import { PaneDivider } from '../contacts/workspace/PaneDivider';

/** Pixelwert eines Tokens — deterministischer Startwert, wie im Kontaktmodul. */
function tokenPx(name: string, fallback: number): number {
  if (typeof window === 'undefined') return fallback;
  const roh = getComputedStyle(document.documentElement).getPropertyValue(name);
  const wert = Number.parseInt(roh, 10);
  return Number.isFinite(wert) ? wert : fallback;
}
import {
  RASTER_LABELS, RASTER_MODI, type RasterModus,
  baueRaster, heute, systemWochenstart, systemZeitzone, termintage,
  verschiebeAnker,
} from './raster';

/** Anzeigereihenfolge des Umschalters wie die Referenz: Tag · Woche · Monat · Jahr. */
const UMSCHALTER_REIHENFOLGE: readonly RasterModus[] =
  [...RASTER_MODI].reverse();

type Ladezustand = 'laedt' | 'bereit' | 'fehler';

interface Bestand {
  von: string | null;
  bis: string | null;
  termine: Termin[];
  truncated: boolean;
}

const LEER: Bestand = { von: null, bis: null, termine: [], truncated: false };

export function CalendarWorkspace() {
  const zone = useMemo(() => systemZeitzone(), []);
  const wochenstart = useMemo(() => systemWochenstart(), []);
  const [modus, setModus] = useState<RasterModus>('month');
  const [anker, setAnker] = useState(() => heute(zone));
  // B2: lesende Tagesauswahl. Reiner Ansichtszustand, keine Schreibsemantik.
  const [gewaehlterTag, setGewaehlterTag] = useState<string | null>(null);
  // B2: verschiebbare Bereichsbreiten — dasselbe Muster wie das Kontaktmodul.
  const grenzen = useMemo(() => ({
    sidebar: {
      start: tokenPx('--pjk-sidebar-width', 220),
      min: tokenPx('--pjk-sidebar-min', 180),
      max: tokenPx('--pjk-sidebar-max', 340),
    },
    detail: {
      start: tokenPx('--pjk-detail-width', 320),
      min: tokenPx('--pjk-detail-min', 260),
      max: tokenPx('--pjk-detail-max', 480),
    },
  }), []);
  const [sidebarBreite, setSidebarBreite] = useState(grenzen.sidebar.start);
  const [detailBreite, setDetailBreite] = useState(grenzen.detail.start);
  // B2-Livebefund 4: die Kalenderliste ist ausblendbar — reiner
  // Ansichtszustand, das vorhandene Trennermuster bleibt unberuehrt.
  const [sidebarVersteckt, setSidebarVersteckt] = useState(false);

  // B2-Livebefund 3: Tagesklick zeigt rechts die Termine des Tages und
  // schliesst eine offene Einzelauswahl.
  const waehleTag = useCallback((tag: string) => {
    setGewaehlterTag(tag);
    setAusgewaehlt(null);
  }, []);
  const [status, setStatus] = useState<ModulStatus | null>(null);
  const [kalender, setKalender] = useState<KalenderZeile[]>([]);
  const [bestand, setBestand] = useState<Bestand>(LEER);
  const [zustand, setZustand] = useState<Ladezustand>('laedt');
  const [versteckt, setVersteckt] = useState<ReadonlySet<string>>(new Set());
  const [ausgewaehlt, setAusgewaehlt] = useState<Termin | null>(null);
  const [suche, setSuche] = useState('');
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<{ text: string; art: 'ok' | 'warnung' | 'fehler' } | null>(null);
  // B3 P1: das CREATE-Formular. Es öffnet nur auf Klick und schreibt nur
  // nach ausdrücklicher Einzelfreigabe (DEC-069, siehe Kopfkommentar).
  const [formularOffen, setFormularOffen] = useState(false);
  // B3 P2: der Termin in Bearbeitung. Öffnet die Update-Maske; geschrieben
  // wird auch hier nur nach ausdrücklicher Einzelfreigabe.
  const [bearbeiteTermin, setBearbeiteTermin] = useState<Termin | null>(null);
  const [loescheTermin, setLoescheTermin] = useState<Termin | null>(null);
  const rasterRef = useRef<HTMLDivElement>(null);

  const raster = useMemo(() => baueRaster(modus, anker, zone, wochenstart),
                         [modus, anker, zone, wochenstart]);
  const heuteTag = useMemo(() => heute(zone), [zone]);

  // Beim Wechsel in die Tagesansicht oeffnet sich der gewaehlte Tag (B2 §9).
  // Ohne Auswahl gilt das bisherige Verhalten unveraendert.
  const wechsleModus = useCallback((m: RasterModus) => {
    if (m === 'day' && gewaehlterTag !== null) setAnker(gewaehlterTag);
    setModus(m);
  }, [gewaehlterTag]);

  // Nur lesen. Weder Mount noch Ansichtswechsel loesen einen Sync aus.
  const laden = useCallback(async (vonUtc: string, bisUtc: string) => {
    try {
      // Erst der kalenderfreie Handshake, dann der Status: `/status` meldet
      // bewusst den ZULETZT BEKANNTEN Bridge-Stand und fragt den Provider
      // nicht. Bei frischem Backend ist das „noch nicht geprueft" — also
      // `bridge_available: false`. Ohne diesen Aufruf zeigte die Ansicht
      // „Bridge nicht verfuegbar", obwohl die Bridge da ist, und bot den
      // Berechtigungsweg deshalb nie an.
      //
      // Der Handshake liest keinen Kalender und startet keinen Sync. Sein
      // Fehlschlag darf die Ansicht nicht in den generischen Fehlerzustand
      // werfen: dann bliebe der Status auf seinem fail-closed Vorwert, und
      // die Ansicht sagt ehrlich, dass die Bridge nicht verfuegbar ist.
      await pruefeBridge().catch(() => undefined);
      const [s, k, t] = await Promise.all([
        ladeStatus(), ladeKalender(), ladeTermine(vonUtc, bisUtc),
      ]);
      setStatus(s);
      setKalender(k.calendars);
      setBestand({ von: t.window.start_utc, bis: t.window.end_utc,
                   termine: t.events, truncated: t.truncated });
      setZustand('bereit');
    } catch {
      setZustand('fehler');
    }
  }, []);

  useEffect(() => {
    void laden(raster.fensterStartUtc, raster.fensterEndeUtc);
  }, [laden, raster.fensterStartUtc, raster.fensterEndeUtc]);

  // Tastaturbedienung wie Apple: Pfeile blättern, T springt auf heute,
  // 1–4 wechseln die Ansicht, Escape schliesst die Auswahl (P-12).
  useEffect(() => {
    const aufTaste = (e: KeyboardEvent) => {
      const ziel = e.target as HTMLElement | null;
      if (ziel && ['INPUT', 'TEXTAREA', 'SELECT'].includes(ziel.tagName)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowLeft') { setAnker((a) => verschiebeAnker(modus, a, -1)); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { setAnker((a) => verschiebeAnker(modus, a, 1)); e.preventDefault(); }
      else if (e.key === 't' || e.key === 'T') { setAnker(heute(zone)); e.preventDefault(); }
      else if (e.key === 'Escape') setAusgewaehlt(null);
      else if (['1', '2', '3', '4'].includes(e.key)) {
        wechsleModus(RASTER_MODI[Number(e.key) - 1]!);
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', aufTaste);
    return () => window.removeEventListener('keydown', aufTaste);
  }, [modus, zone, wechsleModus]);

  const sichtbar = useMemo(() => {
    const suchbegriff = suche.trim().toLowerCase();
    return bestand.termine.filter((t) => {
      if (versteckt.has(t.calendar_id)) return false;
      if (suchbegriff === '') return true;
      // Suche ueber Titel, Ort, Notiz und Teilnehmer (P-4).
      const felder = [t.title, t.location, t.notes,
                      ...t.attendees.map((a) => a.display_name),
                      ...t.attendees.map((a) => a.raw_address)];
      return felder.some((f) => (f ?? '').toLowerCase().includes(suchbegriff));
    });
  }, [bestand.termine, versteckt, suche]);

  const termineProTag = useMemo(() => {
    const map = new Map<string, Termin[]>();
    for (const t of sichtbar) {
      for (const tag of termintage(t, zone)) {
        const liste = map.get(tag);
        if (liste) liste.push(t);
        else map.set(tag, [t]);
      }
    }
    // Ganztaegige zuerst, dann chronologisch — wie Apple.
    for (const liste of map.values()) {
      liste.sort((a, b) => (a.is_all_day === b.is_all_day
        ? a.starts_at_utc.localeCompare(b.starts_at_utc)
        : a.is_all_day ? -1 : 1));
    }
    return map;
  }, [sichtbar, zone]);

  const umschalten = useCallback((id: string) => {
    setVersteckt((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const berechtigungAnfragen = useCallback(async () => {
    setLaeuft(true);
    try {
      const r = await frageBerechtigungAn();
      setMeldung(r.granted
        ? { text: 'Zugriff erteilt.', art: 'ok' }
        : r.prompt_attempted
          ? { text: 'Zugriff nicht erteilt.', art: 'fehler' }
          : {
            text: 'macOS hat bereits entschieden und zeigt keinen Dialog mehr. '
              + 'Systemeinstellungen → Datenschutz & Sicherheit → Kalender.',
            art: 'warnung',
          });
      await laden(raster.fensterStartUtc, raster.fensterEndeUtc);
    } catch {
      setMeldung({ text: 'Die Bridge ist nicht erreichbar.', art: 'fehler' });
    } finally {
      setLaeuft(false);
    }
  }, [laden, raster.fensterStartUtc, raster.fensterEndeUtc]);

  const jetztSynchronisieren = useCallback(async () => {
    setLaeuft(true);
    try {
      const past = status?.default_window.past_days ?? 90;
      const future = status?.default_window.future_days ?? 365;
      const b: LaufBericht = await synchronisiere(past, future);
      // `outcome` ist die eine Gesamtaussage — ein HTTP-200 beweist keinen
      // Erfolg, und die Teilergebnisse selbst zusammenzurechnen waere genau
      // der Fehler, den der Bericht vermeidet.
      setMeldung(
        b.outcome === 'completed'
          ? { text: `${b.events_seen} Termin(e) gelesen · ${b.created} neu, `
              + `${b.updated} geändert, ${b.tombstoned} entfernt.`, art: 'ok' }
          : b.outcome === 'partial'
            ? { text: `Unvollständig: ${b.calendars_complete} von `
                + `${b.calendars_total} Kalendern gelesen. Aus den übrigen `
                + 'wurde nichts abgeleitet.', art: 'warnung' }
            : { text: 'Der Lauf ist gescheitert — der Bestand ist unverändert.',
                art: 'fehler' });
      await laden(raster.fensterStartUtc, raster.fensterEndeUtc);
    } catch {
      setMeldung({ text: 'Die Bridge ist nicht erreichbar.', art: 'fehler' });
    } finally {
      setLaeuft(false);
    }
  }, [status, laden, raster.fensterStartUtc, raster.fensterEndeUtc]);

  if (zustand === 'laedt') {
    return (
      <div className="p-6 text-sm" style={{ color: 'var(--pjk-ink-dim)' }}
        data-testid="kalender-laedt">Kalender wird geladen …</div>
    );
  }
  if (zustand === 'fehler') {
    return (
      <div className="p-6 text-sm" data-testid="kalender-fehler">
        <p style={{ color: 'var(--pjk-ink)' }}>Der Kalender ist nicht erreichbar.</p>
        <button type="button" className="mt-2 underline text-xs"
          onClick={() => void laden(raster.fensterStartUtc, raster.fensterEndeUtc)}>
          Erneut versuchen
        </button>
      </div>
    );
  }

  const darfLesen = status?.can_read === true;
  const bridgeDa = status?.bridge_available === true;

  return (
    <div className="flex flex-col h-full min-h-0" data-testid="kalender-workspace"
      style={{ background: 'var(--pjk-surface)' }}>
      {/* ── Toolbar, wie die Referenz: Umschalter mittig, Navigation und
             Suche rechts. Der Monatstitel steht gross im Inhaltsbereich. ── */}
      <header className="grid items-center gap-2 flex-shrink-0 px-3"
        style={{ height: 'var(--pjk-toolbar-height)',
                 gridTemplateColumns: '1fr auto 1fr',
                 borderBottom: '1px solid var(--pjk-line)',
                 paddingRight: 'var(--pjk-toolbar-reserve)' }}>
        <div className="justify-self-start flex items-center gap-2">
          {/* B3 P1: der Einstieg in den Schreibpfad — nur sichtbar, wenn
              lesbarer Bestand UND Bridge da sind. Der Klick öffnet nur das
              Formular; geschrieben wird erst nach der Einzelfreigabe. */}
          {darfLesen && bridgeDa && (
            <button type="button" aria-label="Neuen Termin anlegen"
              onClick={() => setFormularOffen(true)}
              className="text-xs px-2 py-1 rounded"
              style={{ border: '1px solid var(--pjk-line)' }}>
              Neuer Termin
            </button>
          )}
          <button type="button"
            aria-label={sidebarVersteckt
              ? 'Kalenderliste einblenden' : 'Kalenderliste ausblenden'}
            onClick={() => setSidebarVersteckt((v) => !v)}
            className="p-1 rounded"
            style={{ color: 'var(--pjk-ink-dim)' }}>
            <PanelLeft size={16} />
          </button>
        </div>

        <div role="tablist" aria-label="Ansicht" className="flex rounded overflow-hidden justify-self-center"
          style={{ border: '1px solid var(--pjk-line)' }}>
          {UMSCHALTER_REIHENFOLGE.map((m) => (
            <button key={m} type="button" role="tab" aria-selected={modus === m}
              onClick={() => wechsleModus(m)} className="text-xs px-2 py-1"
              style={{
                // Systemakzentfarbe statt Grau (B2-Livebefund): Highlight
                // folgt der macOS-Farbsprache und loest in WebKit 15 auf.
                background: modus === m ? 'var(--pjk-auswahl)' : 'transparent',
                color: modus === m ? 'var(--pjk-auswahl-text)' : 'var(--pjk-ink)',
              }}>{RASTER_LABELS[m]}</button>
          ))}
        </div>

        <div className="flex items-center gap-2 justify-self-end">
          <button type="button" aria-label="Zurück" className="px-2 py-1 text-sm"
            onClick={() => setAnker((a) => verschiebeAnker(modus, a, -1))}>‹</button>
          <button type="button" className="px-2 py-1 text-xs"
            onClick={() => setAnker(heute(zone))}>Heute</button>
          <button type="button" aria-label="Weiter" className="px-2 py-1 text-sm"
            onClick={() => setAnker((a) => verschiebeAnker(modus, a, 1))}>›</button>
          <input type="search" value={suche} placeholder="Suchen"
            onChange={(e) => setSuche(e.target.value)}
            aria-label="Termine durchsuchen"
            className="text-xs px-2 py-1 rounded"
            style={{ width: 'var(--pjk-search-width)',
                     border: '1px solid var(--pjk-line)',
                     background: 'var(--pjk-surface-2)', color: 'var(--pjk-ink)' }} />
          <button type="button" onClick={() => void jetztSynchronisieren()}
            disabled={laeuft || !darfLesen} className="text-xs px-2 py-1 rounded"
            style={{ border: '1px solid var(--pjk-line)',
                     opacity: laeuft || !darfLesen ? 0.5 : 1 }}>
            {laeuft ? 'Läuft …' : 'Aktualisieren'}
          </button>
        </div>
      </header>

      {/* ── Meldungen: immer als HANDLUNG, nie als Zustand ── */}
      {meldung !== null && (
        <p role="status" data-testid="kalender-meldung"
          className="text-[11px] px-3 py-1 flex-shrink-0"
          style={{
            borderBottom: '1px solid var(--pjk-line-soft)',
            color: meldung.art === 'fehler' ? 'var(--color-error)'
              : meldung.art === 'warnung' ? 'var(--color-warning, #b8860b)'
                : 'var(--pjk-ink-dim)',
          }}>
          Letzte Aktion: {meldung.text}
        </p>
      )}

      {/* ── Berechtigungszustände: Grund UND nächster Schritt ── */}
      {!darfLesen && (
        <div data-testid="kalender-berechtigung"
          className="px-3 py-2 text-[11px] flex-shrink-0"
          style={{ borderBottom: '1px solid var(--pjk-line-soft)',
                   background: 'var(--pjk-surface-2)' }}>
          {!bridgeDa ? (
            <span style={{ color: 'var(--pjk-ink)' }}>
              Die Kalender-Bridge ist auf diesem Rechner nicht verfügbar —
              deshalb sind hier keine Termine zu sehen. Es ist nicht gesagt,
              dass dein Kalender leer ist.
            </span>
          ) : status?.authorization_status === 'not_determined' ? (
            <span>
              <span style={{ color: 'var(--pjk-ink)' }}>
                macOS hat den Kalenderzugriff noch nicht erteilt.
              </span>{' '}
              <button type="button" onClick={() => void berechtigungAnfragen()}
                disabled={laeuft} className="underline">Zugriff anfragen</button>
            </span>
          ) : status?.authorization_status === 'write_only' ? (
            <span style={{ color: 'var(--pjk-ink)' }}>
              macOS hat nur Schreibzugriff erteilt. Zum Anzeigen von Terminen
              verlangt das System Vollzugriff: Systemeinstellungen →
              Datenschutz &amp; Sicherheit → Kalender.
            </span>
          ) : (
            <span style={{ color: 'var(--pjk-ink)' }}>
              macOS hat den Kalenderzugriff abgelehnt ({status?.authorization_status}).
              Was tun: Systemeinstellungen → Datenschutz &amp; Sicherheit →
              Kalender → Jarvis freigeben.
            </span>
          )}
        </div>
      )}

      {bestand.truncated && (
        <p className="px-3 py-1 text-[11px] flex-shrink-0"
          style={{ color: 'var(--color-warning, #b8860b)' }}>
          Unvollständig geladen — es können Termine fehlen. Kleineren Zeitraum wählen.
        </p>
      )}

      {/* ── Drei Bereiche: Liste · Raster · Detail, Breiten verschiebbar,
             Liste ausblendbar ── */}
      <div className="grid flex-1 min-h-0"
        style={{ gridTemplateColumns: sidebarVersteckt
          ? `minmax(var(--pjk-grid-min), 1fr) auto ${detailBreite}px`
          : `${sidebarBreite}px auto minmax(var(--pjk-grid-min), 1fr) auto ${detailBreite}px` }}>
        {!sidebarVersteckt && (
          <div className="min-w-0">
            <CalendarSidebar kalender={kalender} versteckt={versteckt}
              aufAendern={umschalten} zone={zone}
              anker={anker} heuteTag={heuteTag} wochenstart={wochenstart}
              aufTag={(tag) => { setAnker(tag); waehleTag(tag); }} />
          </div>
        )}

        {!sidebarVersteckt && (
          <PaneDivider label="Kalenderliste anpassen" wert={sidebarBreite}
            min={grenzen.sidebar.min} max={grenzen.sidebar.max}
            onChange={setSidebarBreite} />
        )}

        <div ref={rasterRef} className="min-w-0 min-h-0 flex flex-col">
          {/* B2: Monatstitel gross und deutlich links im Inhaltsbereich. */}
          <h1 className="flex-shrink-0 px-4 pt-3 pb-1 text-2xl font-bold truncate"
            style={{ color: 'var(--pjk-ink)' }}>{raster.titel}</h1>
          {/* Die Rasterflaeche scrollt. Bis 2026-08-16 tat sie das nicht, und
              was nicht hineinpasste, war unerreichbar: Die Zeitachse ist 24
              Stunden a --pjk-hour-height hoch, also weit mehr als die Flaeche,
              und schon die Monatsansicht lief gemessen 34 px ueber. Ohne
              Scrollcontainer schnitt das `overflow-hidden` der Schale sie
              einfach ab — kein Fehler, kein Hinweis, nur weg. `min-h-0` an der
              Spalte gehoert dazu: ohne sie kann ein Flex-Kind nicht unter
              seine Inhaltshoehe schrumpfen und der Ueberlauf entstuende gar
              nicht erst am scrollenden Element. */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            {modus === 'month' && (
              <MonatsRaster raster={raster} termineProTag={termineProTag} zone={zone}
                heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
                aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null}
                wochenstart={wochenstart} gewaehlterTag={gewaehlterTag}
                aufTagAuswahl={waehleTag} />
            )}
            {(modus === 'week' || modus === 'day') && (
              <ZeitRaster raster={raster} termineProTag={termineProTag} zone={zone}
                heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
                aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null}
                wochenstart={wochenstart} gewaehlterTag={gewaehlterTag}
                aufTagAuswahl={waehleTag} />
            )}
            {modus === 'year' && (
              <JahresRaster raster={raster} termineProTag={termineProTag} zone={zone}
                heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
                aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null}
                wochenstart={wochenstart} gewaehlterTag={gewaehlterTag}
                aufTagAuswahl={waehleTag}
                aufTag={(tag) => { setGewaehlterTag(tag); setAnker(tag); setModus('day'); }} />
            )}
          </div>
        </div>

        <PaneDivider label="Termindetails anpassen" wert={detailBreite}
          min={grenzen.detail.min} max={grenzen.detail.max}
          onChange={setDetailBreite} richtung="rechts" />

        <div className="min-w-0">
          {ausgewaehlt !== null ? (
            <TerminDetail termin={ausgewaehlt} zone={zone}
              aufBearbeiten={darfLesen && bridgeDa
                ? (t) => setBearbeiteTermin(t) : undefined}
              aufLoeschen={darfLesen && bridgeDa
                ? (t) => setLoescheTermin(t) : undefined} />
          ) : (
            <TagesListe tag={gewaehlterTag}
              termine={gewaehlterTag !== null
                ? (termineProTag.get(gewaehlterTag) ?? []) : []}
              zone={zone} aufAuswahl={setAusgewaehlt} />
          )}
        </div>
      </div>

      {/* ── B3 P1: das CREATE-Formular mit Freigabefluss ── */}
      {formularOffen && (
        <TerminFormular kalender={kalender} zone={zone}
          vorbelegterTag={gewaehlterTag ?? heuteTag}
          aufSchliessen={() => setFormularOffen(false)}
          aufErfolg={() => {
            // Kein Auto-Sync: nach dem Settle ist der gespeicherte Bestand
            // serverseitig nachgeführt — Neu-LESEN genügt. „Aktualisieren"
            // bleibt der einzige Weg zum Provider-Sync.
            setMeldung({ text: 'Termin angelegt.', art: 'ok' });
            void laden(raster.fensterStartUtc, raster.fensterEndeUtc);
          }} />
      )}

      {/* ── B3 P3: der LÖSCH-Dialog mit Probe und Freigabefluss ── */}
      {loescheTermin !== null && (
        <TerminLoeschen termin={loescheTermin} zone={zone}
          aufSchliessen={() => setLoescheTermin(null)}
          aufErfolg={() => {
            setMeldung({ text: 'Termin gelöscht.', art: 'ok' });
            // Das Detail zeigt sonst den GELÖSCHTEN Termin — schliessen
            // und den nachgeführten Bestand neu lesen.
            setAusgewaehlt(null);
            void laden(raster.fensterStartUtc, raster.fensterEndeUtc);
          }} />
      )}

      {/* ── B3 P2: die UPDATE-Maske (Delta) mit Freigabefluss ── */}
      {bearbeiteTermin !== null && (
        <TerminFormular kalender={kalender} zone={zone}
          vorbelegterTag={gewaehlterTag ?? heuteTag}
          bearbeite={bearbeiteTermin}
          aufSchliessen={() => setBearbeiteTermin(null)}
          aufErfolg={() => {
            setMeldung({ text: 'Termin aktualisiert.', art: 'ok' });
            // Das Detail zeigt sonst den VERALTETEN Termin — schliessen
            // und den nachgeführten Bestand neu lesen.
            setAusgewaehlt(null);
            void laden(raster.fensterStartUtc, raster.fensterEndeUtc);
          }} />
      )}
    </div>
  );
}

export default CalendarWorkspace;

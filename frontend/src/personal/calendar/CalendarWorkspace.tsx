// Dreispaltiger Kalender-Workspace: Kalenderliste · Raster · Detail.
//
// Dieser Baustein besitzt den Datenzustand, die Auswahl, den Ansichtsmodus und
// den Anker. Die Flächen in `panes.tsx` sind reine Präsentation.
//
// Verbindlich:
//  · KEIN Auto-Sync. Der Mount und jeder Ansichtswechsel LESEN nur den
//    gespeicherten Bestand. Synchronisiert wird ausschliesslich auf Klick.
//  · Kein Timer, kein Poller, kein Intervall.
//  · Die Oberfläche zeigt, welchen Zeitraum sie kennt. Ein Kalender, der so
//    tut, als kenne er alles, lügt.
//  · Sichtbarkeitsfilter sind reine Anzeige und werden nirgends gespeichert.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './tokens.css';
import {
  type KalenderZeile, type LaufBericht, type ModulStatus, type Termin,
  frageBerechtigungAn, ladeKalender, ladeStatus, ladeTermine, synchronisiere,
} from './api';
import {
  CalendarSidebar, JahresRaster, MonatsRaster, TerminDetail, ZeitRaster,
} from './panes';
import {
  RASTER_LABELS, RASTER_MODI, type RasterModus,
  baueRaster, heute, systemZeitzone, termintage, verschiebeAnker,
} from './raster';

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
  const [modus, setModus] = useState<RasterModus>('month');
  const [anker, setAnker] = useState(() => heute(zone));
  const [status, setStatus] = useState<ModulStatus | null>(null);
  const [kalender, setKalender] = useState<KalenderZeile[]>([]);
  const [bestand, setBestand] = useState<Bestand>(LEER);
  const [zustand, setZustand] = useState<Ladezustand>('laedt');
  const [versteckt, setVersteckt] = useState<ReadonlySet<string>>(new Set());
  const [ausgewaehlt, setAusgewaehlt] = useState<Termin | null>(null);
  const [suche, setSuche] = useState('');
  const [laeuft, setLaeuft] = useState(false);
  const [meldung, setMeldung] = useState<{ text: string; art: 'ok' | 'warnung' | 'fehler' } | null>(null);
  const rasterRef = useRef<HTMLDivElement>(null);

  const raster = useMemo(() => baueRaster(modus, anker, zone), [modus, anker, zone]);
  const heuteTag = useMemo(() => heute(zone), [zone]);

  // Nur lesen. Weder Mount noch Ansichtswechsel loesen einen Sync aus.
  const laden = useCallback(async (vonUtc: string, bisUtc: string) => {
    try {
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
        setModus(RASTER_MODI[Number(e.key) - 1]!);
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', aufTaste);
    return () => window.removeEventListener('keydown', aufTaste);
  }, [modus, zone]);

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
    <div className="flex flex-col h-full min-h-0" data-testid="kalender-workspace">
      {/* ── Toolbar ── */}
      <header className="flex items-center gap-2 flex-shrink-0 px-3"
        style={{ height: 'var(--pjk-toolbar-height)',
                 borderBottom: '1px solid var(--pjk-line)',
                 paddingRight: 'var(--pjk-toolbar-reserve)' }}>
        <button type="button" aria-label="Zurück" className="px-2 py-1 text-sm"
          onClick={() => setAnker((a) => verschiebeAnker(modus, a, -1))}>‹</button>
        <button type="button" className="px-2 py-1 text-xs"
          onClick={() => setAnker(heute(zone))}>Heute</button>
        <button type="button" aria-label="Weiter" className="px-2 py-1 text-sm"
          onClick={() => setAnker((a) => verschiebeAnker(modus, a, 1))}>›</button>
        <h1 className="text-sm font-medium ml-1 truncate"
          style={{ color: 'var(--pjk-ink)' }}>{raster.titel}</h1>

        <div className="flex-1" />

        <input type="search" value={suche} placeholder="Suchen"
          onChange={(e) => setSuche(e.target.value)}
          aria-label="Termine durchsuchen"
          className="text-xs px-2 py-1 rounded"
          style={{ width: 'var(--pjk-search-width)',
                   border: '1px solid var(--pjk-line)',
                   background: 'var(--pjk-surface-2)', color: 'var(--pjk-ink)' }} />

        <div role="tablist" aria-label="Ansicht" className="flex rounded overflow-hidden"
          style={{ border: '1px solid var(--pjk-line)' }}>
          {RASTER_MODI.map((m) => (
            <button key={m} type="button" role="tab" aria-selected={modus === m}
              onClick={() => setModus(m)} className="text-xs px-2 py-1"
              style={{
                background: modus === m ? 'var(--pjk-ink)' : 'transparent',
                color: modus === m ? 'var(--pjk-surface)' : 'var(--pjk-ink)',
              }}>{RASTER_LABELS[m]}</button>
          ))}
        </div>

        <button type="button" onClick={() => void jetztSynchronisieren()}
          disabled={laeuft || !darfLesen} className="text-xs px-2 py-1 rounded"
          style={{ border: '1px solid var(--pjk-line)',
                   opacity: laeuft || !darfLesen ? 0.5 : 1 }}>
          {laeuft ? 'Läuft …' : 'Aktualisieren'}
        </button>
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

      {/* ── Drei Spalten ── */}
      <div className="flex flex-1 min-h-0">
        <div style={{ width: 'var(--pjk-sidebar-width)', flexShrink: 0 }}>
          <CalendarSidebar kalender={kalender} versteckt={versteckt}
            aufAendern={umschalten} zone={zone} />
        </div>

        <div ref={rasterRef} className="flex-1 min-w-0"
          style={{ minWidth: 'var(--pjk-grid-min)' }}>
          {modus === 'month' && (
            <MonatsRaster raster={raster} termineProTag={termineProTag} zone={zone}
              heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
              aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null} />
          )}
          {(modus === 'week' || modus === 'day') && (
            <ZeitRaster raster={raster} termineProTag={termineProTag} zone={zone}
              heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
              aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null} />
          )}
          {modus === 'year' && (
            <JahresRaster raster={raster} termineProTag={termineProTag} zone={zone}
              heuteTag={heuteTag} bekanntVon={bestand.von} bekanntBis={bestand.bis}
              aufAuswahl={setAusgewaehlt} ausgewaehlt={ausgewaehlt?.id ?? null}
              aufTag={(tag) => { setAnker(tag); setModus('day'); }} />
          )}
        </div>

        <div style={{ width: 'var(--pjk-detail-width)', flexShrink: 0 }}>
          <TerminDetail termin={ausgewaehlt} zone={zone} />
        </div>
      </div>

      {/* ── Herkunft und Grenze bleiben sichtbar ── */}
      <footer className="flex-shrink-0 px-3 py-1 text-[10px]"
        style={{ borderTop: '1px solid var(--pjk-line-soft)',
                 color: 'var(--pjk-ink-dim)' }}>
        Herkunft: Apple Kalender · lokal über EventKit · in dieser Fassung nur
        lesend. Geladener Zeitraum: {raster.titel}. Schraffierte Tage sind nicht
        geladen — sie sind nicht „frei", sondern unbekannt.
      </footer>
    </div>
  );
}

export default CalendarWorkspace;

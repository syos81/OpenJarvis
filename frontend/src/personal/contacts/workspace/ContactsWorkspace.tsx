// Dreispaltiger Kontakte-Workspace: Sidebar · Liste · Detail.
//
// Dieser Baustein besitzt den Datenzustand (über eine ContactsDataSource),
// die Auswahl, die Suche und den Bearbeitungszustand. Die Panes sind reine
// Präsentation. Alles Technische (Freigaben, Vorgänge, Berechtigung,
// Demo-Modus) liegt in der getrennten Statusfläche.
//
// Spaltenbreiten starten deterministisch aus den Tokens und werden bewusst
// nicht persistiert: es existiert keine Contacts-eigene Präferenzschicht,
// und der globale Store bleibt für dieses Modul tabu (Statiktest).

import {
  useEffect, useMemo, useRef, useState,
} from 'react';
import type {
  Capabilities, ContactDetail, ContactSummary, PreparedMutation, RoleCount,
} from '../api';
import { EmptyState, ErrorState, LoadingState } from '../components';
import type { ContactsDataSource } from '../data/source';
import { apiDataSource } from '../data/source';
import { fixtureDataSource } from '../data/fixtureSource';
import { sortiereKontakte } from '../data/sortierung';
import { ContactsSidebar, type SidebarAuswahl } from '../sidebar/ContactsSidebar';
import { ContactsListPane } from '../list/ContactsListPane';
import { KontextMenue } from '../list/KontextMenue';
import type { KontextEintrag } from '../list/KontextMenue';
import { ContactDetailPane } from '../detail/ContactDetailPane';
import { ContactEditor } from '../editor/ContactEditor';
// PreviewDialog wird hier nicht mehr eingehaengt: eigene Handlungen laufen
// nach ihrer einen Bestaetigung durch. Freigaben zu Vorgaengen, die Jarvis
// selbst vorbereitet hat, entscheidet weiterhin die Statusflaeche.
import { CreateDialog, DeleteBestaetigung } from '../editor/dialogs';
import { ContactsStatusSurface } from '../status/ContactsStatusSurface';
import { ContactsToolbar } from './ContactsToolbar';
import { PaneDivider } from './PaneDivider';
import type { Fehlerbild } from './fehler';
import { fehlerbild } from './fehler';

const SUCH_VERZOEGERUNG_MS = 150;

function tokenPx(name: string, fallback: number): number {
  if (typeof window === 'undefined') return fallback;
  const roh = getComputedStyle(document.documentElement).getPropertyValue(name);
  const n = Number.parseFloat(roh);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

/**
 * Die Datenquelle des ersten Renders.
 *
 * Ein Dev-Fixture-Szenario (`?pjcDemo=<n>`) muss **vor** dem ersten Render
 * feststehen: Die Lade-Effekte des Workspace laufen im selben Commit und
 * noch vor dem Szenario-Effekt. Wird die Quelle erst dort getauscht, hat
 * die API-Quelle bereits vier lesende Anfragen abgesetzt (Kontakte,
 * Kategorien, Capabilities, Freigaben) — für einen isolierten
 * Fixture-Lauf unnötig und irreführend.
 *
 * Ausschliesslich unter `import.meta.env.DEV`; im Produktionsbundle wird
 * der Block zu totem Code und der Parametername verschwindet vollständig.
 * Der bewusst aktivierbare Produkt-Demo-Modus (Statusfläche, zwei
 * Schritte) ist davon unberührt und bleibt standardmässig aus.
 */
export function startQuelle(): ContactsDataSource {
  if (import.meta.env.DEV && typeof window !== 'undefined') {
    const roh = new URLSearchParams(window.location.search).get('pjcDemo');
    const anzahl = Number(roh);
    if (roh !== null && Number.isFinite(anzahl) && anzahl > 0) {
      return fixtureDataSource(anzahl);
    }
  }
  return apiDataSource();
}

export function ContactsWorkspace({ testListenHoehe }: {
  /** Nur für Tests ohne Layout (jsdom): Höhe der Liste in Pixeln. */
  testListenHoehe?: number;
}) {
  // ── Quelle und Grunddaten ────────────────────────────────────────────────
  const [quelle, setQuelle] = useState<ContactsDataSource>(startQuelle);
  const demoModus = quelle.art === 'fixtures';

  const [kontakte, setKontakte] = useState<ContactSummary[]>([]);
  const [ladezustand, setLadezustand] = useState<'laden' | 'bereit' | 'fehler'>('laden');
  const [ladeFehler, setLadeFehler] = useState<Fehlerbild | null>(null);
  const [kategorien, setKategorien] = useState<RoleCount[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [offeneFreigaben, setOffeneFreigaben] = useState(0);
  const [nachladen, setNachladen] = useState(0);

  // Stale-Guard: Wechselt die Quelle (Demo-Modus) oder läuft ein neuer
  // Ladevorgang an, darf ein noch ausstehendes altes Ergebnis — Erfolg wie
  // Fehler — den Zustand nicht mehr berühren.
  useEffect(() => {
    let aktiv = true;
    setLadezustand('laden');
    setLadeFehler(null);
    quelle.ladeAlle()
      .then((alle) => {
        if (!aktiv) return;
        setKontakte(sortiereKontakte(alle));
        setLadezustand('bereit');
      })
      .catch((e) => {
        if (!aktiv) return;
        setLadeFehler(fehlerbild(e));
        setLadezustand('fehler');
      });
    return () => { aktiv = false; };
  }, [quelle, nachladen]);

  useEffect(() => {
    let aktiv = true;
    quelle.kategorien()
      .then((k) => { if (aktiv) setKategorien(k); })
      .catch(() => { if (aktiv) setKategorien([]); });
    // Fail-closed: unbekannte Capabilities gelten als „nicht verfügbar".
    quelle.capabilities()
      .then((c) => { if (aktiv) setCaps(c); })
      .catch(() => { if (aktiv) setCaps(null); });
    quelle.listApprovals()
      .then((a) => {
        if (!aktiv) return;
        setOffeneFreigaben(
          a.filter((e) => e.state === 'awaiting_approval' && !e.is_expired).length,
        );
      })
      .catch(() => { if (aktiv) setOffeneFreigaben(0); });
    return () => { aktiv = false; };
  }, [quelle, nachladen]);

  // ── Suche (entprellt, lokal über den geladenen Zustand) ──────────────────
  const [sucheEingabe, setSucheEingabe] = useState('');
  const [suchErgebnis, setSuchErgebnis] = useState<ContactSummary[] | null>(null);
  const suchfeld = useRef<HTMLInputElement>(null);
  const fokusListe = () => {
    document.querySelector<HTMLElement>('[data-testid="contacts-liste"]')?.focus();
  };

  useEffect(() => {
    const q = sucheEingabe.trim();
    if (q === '') {
      setSuchErgebnis(null);
      return undefined;
    }
    let aktiv = true;
    const timer = setTimeout(() => {
      quelle.suche(q)
        .then((r) => { if (aktiv) setSuchErgebnis(sortiereKontakte(r)); })
        .catch(() => { if (aktiv) setSuchErgebnis([]); });
    }, SUCH_VERZOEGERUNG_MS);
    return () => { aktiv = false; clearTimeout(timer); };
  }, [sucheEingabe, quelle]);

  // ── Sidebar-Filter und sichtbare Liste ───────────────────────────────────
  const [sidebarAuswahl, setSidebarAuswahl] = useState<SidebarAuswahl>({ art: 'alle' });

  const konten = useMemo(() => {
    const s = new Set<string>();
    for (const k of kontakte) for (const ref of k.account_refs) s.add(ref);
    return [...s].sort();
  }, [kontakte]);

  const sichtbar = useMemo(() => {
    const basis = suchErgebnis ?? kontakte;
    if (sidebarAuswahl.art === 'konto') {
      return basis.filter((k) => k.account_refs.includes(sidebarAuswahl.ref));
    }
    if (sidebarAuswahl.art === 'kategorie') {
      return basis.filter((k) => k.roles.includes(sidebarAuswahl.rolle));
    }
    return basis;
  }, [suchErgebnis, kontakte, sidebarAuswahl]);

  // ── Auswahl und Detail ───────────────────────────────────────────────────
  const [auswahlId, setAuswahlId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [detailFehler, setDetailFehler] = useState<Fehlerbild | null>(null);
  const [detailLaedt, setDetailLaedt] = useState(false);

  useEffect(() => {
    if (!auswahlId) {
      setDetail(null);
      return undefined;
    }
    let aktiv = true;
    setDetailLaedt(true);
    setDetailFehler(null);
    quelle.detail(auswahlId)
      .then((d) => { if (aktiv) setDetail(d); })
      .catch((e) => { if (aktiv) setDetailFehler(fehlerbild(e)); })
      .finally(() => { if (aktiv) setDetailLaedt(false); });
    return () => { aktiv = false; };
  }, [auswahlId, quelle, nachladen]);

  const nichtImFilter = Boolean(
    auswahlId && detail && !sichtbar.some((k) => k.id === auswahlId),
  );

  // ── Bearbeitung und Dialoge ──────────────────────────────────────────────
  const [bearbeitet, setBearbeitet] = useState(false);
  const [editorFehler, setEditorFehler] = useState<Fehlerbild | null>(null);
  const [editorSendet, setEditorSendet] = useState(false);
  const [editorDreckig, setEditorDreckig] = useState(false);
  const [loeschenOffen, setLoeschenOffen] = useState(false);
  const [kontextmenue, setKontextmenue] =
    useState<{ id: string; x: number; y: number } | null>(null);
  const [neuMenue, setNeuMenue] = useState<{ x: number; y: number } | null>(null);
  const [anlegenOffen, setAnlegenOffen] = useState(false);
  const [statusOffen, setStatusOffen] = useState(false);
  //: Nach einer Freigabe soll die Fläche beim Vorgang aufgehen, nicht bei
  //: der Quelle — der Mensch hat gerade entschieden und will ausführen.
  const [statusStart, setStatusStart] = useState<'vorgaenge' | undefined>();
  const [aktionsFehler, setAktionsFehler] = useState<Fehlerbild | null>(null);

  /**
   * Schliesst einen vorbereiteten Vorgang ohne weiteren Klick ab.
   *
   * Der Mensch hat unmittelbar zuvor selbst gehandelt — „Fertig" im Editor,
   * „Löschen" im Bestätigungsdialog, „Anlegen" im Anlegedialog. Diese
   * Handlung **ist** die Freigabe; sie wird mit `decision_actor` in der
   * Auditspur festgehalten und kostet nur keinen zweiten Klick mehr.
   *
   * Ausdrücklich begrenzt auf Vorgänge, die der Mensch selbst ausgelöst hat
   * (`initiation_context = user_direct`). Was Jarvis von sich aus vorbereitet,
   * behält den sichtbaren Freigabeweg — dort ist die Zustimmung der ganze
   * Punkt (ADR-0026, DEC-053).
   */
  const abschliessen = async (m: PreparedMutation) => {
    setAktionsFehler(null);
    try {
      await quelle.approve(m.mutation_id, 'desktop-user');
      await quelle.execute(m.mutation_id, m.command === 'delete');
    } catch (e) {
      // Fehlschläge bleiben sichtbar: fail-closed heisst nicht stillschweigend.
      setAktionsFehler(fehlerbild(e));
    } finally {
      setNachladen((n) => n + 1);
    }
  };

  const fertig = async (felder: Record<string, unknown>) => {
    if (!detail) return;
    setEditorSendet(true);
    setEditorFehler(null);
    try {
      const m = await quelle.prepareUpdate(detail.id, {
        expectedRevision: detail.revision,
        fields: felder,
      });
      setBearbeitet(false);
      await abschliessen(m);
    } catch (e) {
      setEditorFehler(fehlerbild(e));
    } finally {
      setEditorSendet(false);
    }
  };

  const rolle = async (fn: () => Promise<{ roles: string[] }>) => {
    if (!detail) return;
    setAktionsFehler(null);
    try {
      const neu = await fn();
      setDetail({ ...detail, roles: neu.roles });
    } catch (e) {
      setAktionsFehler(fehlerbild(e));
    }
  };

  // ── Spaltenbreiten (deterministische Startwerte aus Tokens) ──────────────
  const grenzen = useMemo(() => ({
    sidebar: {
      start: tokenPx('--pjc-sidebar-width', 200),
      min: tokenPx('--pjc-sidebar-min', 160),
      max: tokenPx('--pjc-sidebar-max', 320),
    },
    liste: {
      start: tokenPx('--pjc-list-width', 280),
      min: tokenPx('--pjc-list-min', 220),
      max: tokenPx('--pjc-list-max', 460),
    },
  }), []);
  const [sidebarBreite, setSidebarBreite] = useState(grenzen.sidebar.start);
  const [listenBreite, setListenBreite] = useState(grenzen.liste.start);

  // ── Demo-Modus ───────────────────────────────────────────────────────────
  const demoStart = (anzahl: number) => {
    setQuelle(fixtureDataSource(anzahl));
    setAuswahlId(null);
    setSidebarAuswahl({ art: 'alle' });
    setSucheEingabe('');
    setBearbeitet(false);
  };
  const demoEnde = () => {
    setQuelle(apiDataSource());
    setAuswahlId(null);
    setSidebarAuswahl({ art: 'alle' });
    setSucheEingabe('');
    setBearbeitet(false);
  };

  // ── Dev-Szenarien für Screenshot-Baselines ───────────────────────────────
  // NUR im Vite-Dev-Betrieb erreichbar (import.meta.env.DEV wird im
  // Produktionsbundle zu `false` und der Block zu totem Code): URL-Parameter
  // stellen deterministische Zustände für die Intel-Strukturbaseline her.
  // Im gepackten Tauri-Betrieb gibt es weder Dev-Flag noch Adresszeile —
  // der Demo-Modus dort läuft ausschliesslich über die Statusfläche.
  const szeneAngewendet = useRef(false);
  useEffect(() => {
    if (!import.meta.env.DEV || szeneAngewendet.current) return;
    const p = new URLSearchParams(window.location.search);
    if (![...p.keys()].some((k) => k.startsWith('pjc'))) return;
    szeneAngewendet.current = true;
    // pjcTheme wird bereits synchron in main.tsx angewendet (vor dem Paint),
    // `pjcDemo` bereits in `startQuelle()` vor dem ersten Render. Hier wird
    // die Quelle deshalb nicht noch einmal getauscht — das erzwaenge einen
    // zweiten Ladevorgang und verwuerfe die Szenario-Auswahl.
    const suche = p.get('pjcSuche');
    if (suche) setSucheEingabe(suche);
    if (p.get('pjcStatus')) setStatusOffen(true);
    const kategorie = p.get('pjcKategorie');
    if (kategorie) setSidebarAuswahl({ art: 'kategorie', rolle: kategorie });
  }, []);

  const szeneAuswahl = useRef(false);
  useEffect(() => {
    if (!import.meta.env.DEV || szeneAuswahl.current) return;
    if (ladezustand !== 'bereit' || sichtbar.length === 0) return;
    const p = new URLSearchParams(window.location.search);
    const idx = Number(p.get('pjcAuswahl'));
    if (!Number.isFinite(idx) || p.get('pjcAuswahl') === null) return;
    szeneAuswahl.current = true;
    const ziel = sichtbar[Math.min(sichtbar.length - 1, Math.max(0, idx))];
    setAuswahlId(ziel.id);
    if (p.get('pjcEditor')) setBearbeitet(true);
  }, [ladezustand, sichtbar]);

  // ── Leere-Zustands-Texte ─────────────────────────────────────────────────
  const leerTitel = sucheEingabe.trim() !== ''
    ? 'Keine Suchtreffer'
    : sidebarAuswahl.art !== 'alle'
      ? 'Keine Kontakte in dieser Auswahl'
      : 'Keine Kontakte';
  const leerHinweis = sucheEingabe.trim() !== ''
    ? 'Suche oder Filter liefern kein Ergebnis.'
    : sidebarAuswahl.art !== 'alle'
      ? undefined
      : 'Es ist noch kein Kontakt synchronisiert. Der erste Abgleich läuft über „Vorgänge & Status".';

  return (
    <div
      data-testid="contacts-workspace"
      onKeyDown={(e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'f') {
          e.preventDefault();
          suchfeld.current?.focus();
        }
      }}
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minWidth: 0,
        overflow: 'hidden',
        backgroundColor: 'var(--pjc-bg-detail)',
      }}
    >
      <ContactsToolbar
        ref={suchfeld}
        suche={sucheEingabe}
        onSuche={setSucheEingabe}
        onSucheEscape={() => {
          if (sucheEingabe !== '') setSucheEingabe('');
          else fokusListe();
        }}
        anlegenSichtbar={Boolean(caps?.create_supported)}
        onAnlegen={(x, y) => setNeuMenue({ x, y })}
        bearbeitenSichtbar={Boolean(
          detail && !detail.is_me_card && detail.writable && caps?.update_supported)}
        onBearbeiten={() => setBearbeitet(true)}
        demoModus={demoModus}
      />

      {/* Grid statt Flex: WKWebView auf macOS 12 zeichnete beim Ziehen der
          Trenner einzelne Flex-Spalten erst nach dem naechsten Klick um
          (Nutzerbefund 2026-08-02). Mit einer einzigen
          grid-template-columns-Angabe haengen alle Spaltenpositionen an
          einer Eigenschaft und bleiben beim Drag konsistent. */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: `${sidebarBreite}px auto ${listenBreite}px auto `
          + `minmax(var(--pjc-detail-min), 1fr)`,
        flex: 1,
        minHeight: 0,
      }}>
        {/* Sidebar */}
        <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>
          <ContactsSidebar
            auswahl={sidebarAuswahl}
            onAuswahl={setSidebarAuswahl}
            konten={konten}
            kategorien={kategorien}
            gesamt={kontakte.length}
            demoModus={demoModus}
            statusOffen={statusOffen}
            onStatusToggle={() => setStatusOffen((o) => !o)}
            offeneFreigaben={offeneFreigaben}
          />
        </div>
        <PaneDivider
          label="Breite der Seitenleiste"
          wert={sidebarBreite}
          min={grenzen.sidebar.min}
          max={grenzen.sidebar.max}
          onChange={setSidebarBreite}
        />

        {/* Liste */}
        <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>
          {ladezustand === 'laden' && <LoadingState label="Kontakte werden geladen" />}
          {ladezustand === 'fehler' && ladeFehler && (
            <ErrorState {...ladeFehler} onRetry={() => setNachladen((n) => n + 1)} />
          )}
          {ladezustand === 'bereit' && (
            <ContactsListPane
              kontakte={sichtbar}
              auswahlId={auswahlId}
              // Ein unberuehrter Editor steht dem Weiterklicken nicht im Weg:
              // dann wird er geschlossen und die Auswahl folgt. Erst wenn
              // etwas getippt wurde, bleibt die Auswahl stehen — sonst
              // zeigte der Editor mit ungesicherten Eingaben ploetzlich auf
              // jemand anderen. So verhaelt sich die Referenz auch.
              onAuswahl={(id) => {
                if (bearbeitet && editorDreckig) return;
                setBearbeitet(false);
                setAuswahlId(id);
              }}
              onEnterDetail={() => {
                const el = document.querySelector<HTMLElement>('[data-testid="contact-detail"]');
                el?.focus?.();
              }}
              leerTitel={leerTitel}
              leerHinweis={leerHinweis}
              testHoehe={testListenHoehe}
              onKontextmenue={(id, x, y) => setKontextmenue({ id, x, y })}
            />
          )}
        </div>
        <PaneDivider
          label="Breite der Kontaktliste"
          wert={listenBreite}
          min={grenzen.liste.min}
          max={grenzen.liste.max}
          onChange={setListenBreite}
        />

        {/* Detail */}
        <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>
          {detailLaedt && <LoadingState label="Kontakt wird geladen" />}
          {!detailLaedt && detailFehler && (
            <ErrorState {...detailFehler}
                        onRetry={() => setNachladen((n) => n + 1)} />
          )}
          {!detailLaedt && !detailFehler && !detail && ladezustand === 'bereit' && (
            <EmptyState title="Kein Kontakt ausgewählt"
                        hint="Wähle links einen Kontakt aus der Liste." />
          )}
          {!detailLaedt && !detailFehler && detail && (
            bearbeitet ? (
              <ContactEditor
                kontakt={detail}
                demoModus={demoModus}
                onFertig={(felder) => void fertig(felder)}
                listenSchreibbar={Boolean(caps?.update_supported)}
                onDreckig={setEditorDreckig}
                onAbbrechen={() => {
                  setBearbeitet(false); setEditorFehler(null);
                  setEditorDreckig(false);
                }}
                sendet={editorSendet}
                fehler={editorFehler}
              />
            ) : (
              <ContactDetailPane
                kontakt={detail}
                caps={caps}
                nichtImFilter={nichtImFilter}
                onBearbeiten={() => setBearbeitet(true)}
                onLoeschen={() => setLoeschenOffen(true)}
                onRolleHinzu={(r) => void rolle(() => quelle.assignRole(detail.id, r))}
                onRolleWeg={(r) => void rolle(() => quelle.removeRole(detail.id, r))}
                fehler={aktionsFehler}
              />
            )
          )}
        </div>
      </div>

      {kontextmenue && detail && detail.id === kontextmenue.id && (
        <KontextMenue
          x={kontextmenue.x}
          y={kontextmenue.y}
          onSchliessen={() => setKontextmenue(null)}
          eintraege={((): KontextEintrag[] => {
            // Dieselbe Regel wie die Knoepfe im Detailbereich. Ein Menue,
            // das mehr anbietet als der Rest der Oberflaeche, waere ein
            // zweiter Wahrheitsstand ueber dieselbe Faehigkeit.
            const schreibbar = !detail.is_me_card && detail.writable;
            const eintraege: KontextEintrag[] = [];
            if (schreibbar && caps?.update_supported) {
              eintraege.push({
                id: 'bearbeiten',
                text: 'Kontaktkarte bearbeiten',
                onAuswahl: () => setBearbeitet(true),
              });
            }
            if (schreibbar && caps?.delete_supported) {
              eintraege.push({
                id: 'loeschen',
                text: 'Kontaktkarte löschen',
                gefaehrlich: true,
                onAuswahl: () => setLoeschenOffen(true),
              });
            }
            return eintraege;
          })()}
        />
      )}

      {neuMenue && (
        <KontextMenue
          x={neuMenue.x}
          y={neuMenue.y}
          onSchliessen={() => setNeuMenue(null)}
          eintraege={[{
            id: 'neuer-kontakt',
            text: 'Neuer Kontakt',
            onAuswahl: () => setAnlegenOffen(true),
          }]}
        />
      )}

      {statusOffen && (
        <ContactsStatusSurface
          quelle={quelle}
          startTab={statusStart ?? (import.meta.env.DEV
            ? (new URLSearchParams(window.location.search).get('pjcStatus') as never)
            : undefined)}
          demoModus={demoModus}
          onClose={() => { setStatusOffen(false); setStatusStart(undefined); }}
          onSynced={() => setNachladen((n) => n + 1)}
          onDemoStart={demoStart}
          onDemoEnde={demoEnde}
        />
      )}

      {loeschenOffen && detail && (
        <DeleteBestaetigung
          kontakt={detail}
          quelle={quelle}
          onClose={() => setLoeschenOffen(false)}
          onPrepared={(m) => { setLoeschenOffen(false); void abschliessen(m); }}
        />
      )}
      {anlegenOffen && (
        <CreateDialog
          caps={caps}
          onClose={() => setAnlegenOffen(false)}
          onPrepared={(m) => { setAnlegenOffen(false); void abschliessen(m); }}
        />
      )}
    </div>
  );
}

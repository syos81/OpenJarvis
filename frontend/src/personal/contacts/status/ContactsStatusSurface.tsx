// Jarvis-Statusfläche: Quelle & Abgleich, Freigaben, Vorgänge, Demo-Modus.
//
// Bewusst von der Apple-Ansicht getrennt: alles Technische — Freigaben,
// Vorgangszustände, Berechtigung, Abgleich, Demo-Modus — lebt hier und
// öffnet sich nur auf ausdrücklichen Klick aus der Toolbar. Die Inhalte
// sind die bewährten Bausteine des Bestands, umgestellt auf die
// Datenquelle; Sicherheitsverträge (kein erneutes Senden, Abgleich als
// einziger Weg beim unbekannten Ausgang, manuelle Abschlüsse) sind
// unverändert übernommen.

import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Loader2, RefreshCw, X } from 'lucide-react';
import * as api from '../api';
import type {
  Approval, Authorization, AuthorizationState, Capabilities, Mutation,
  MutationDetail, SyncRun, SyncStatus,
} from '../api';
import {
  Chip, COMMAND_LABELS, EmptyState, ErrorState, LoadingState, StateChip,
  Zielangabe,
} from '../components';
import { aktionsKnopf } from '../detail/ContactDetailPane';
import type { ContactsDataSource } from '../data/source';
import type { Fehlerbild } from '../workspace/fehler';
import { fehlerbild } from '../workspace/fehler';
import { freigeben } from '../settings/freigabe';
import { Kontingentanzeige } from '../settings/Kontingentanzeige';

const AUTH_TEXT: Record<AuthorizationState, { titel: string; hinweis: string }> = {
  notDetermined: {
    titel: 'Noch nicht entschieden',
    hinweis: 'Personal Jarvis hat noch nie auf deine Kontakte zugegriffen. '
      + 'Du entscheidest gleich selbst im macOS-Dialog.',
  },
  authorized: {
    titel: 'Zugriff erlaubt',
    hinweis: 'Kontakte können gelesen werden.',
  },
  denied: {
    titel: 'Zugriff abgelehnt',
    hinweis: 'Ändern lässt sich das nur in den Systemeinstellungen unter '
      + 'Datenschutz & Sicherheit → Kontakte.',
  },
  restricted: {
    titel: 'Zugriff eingeschränkt',
    hinweis: 'Der Zugriff ist auf diesem Mac durch eine Richtlinie gesperrt.',
  },
  unknown: {
    titel: 'Status unbekannt',
    hinweis: 'Der Status konnte nicht gelesen werden. Er wird nicht geraten.',
  },
};

const SYNC_MODUS: Record<string, string> = {
  initial_import: 'Erstimport',
  full_diff: 'Vollabgleich',
  delta: 'Änderungsabgleich',
};

// ── Quelle & Abgleich (nur API-Betrieb; Demo zeigt einen Hinweis) ──────────
function SyncPanel({ onSynced }: { onSynced: () => void }) {
  const [auth, setAuth] = useState<Authorization | null>(null);
  const [status, setStatus] = useState<SyncStatus[]>([]);
  const [lauf, setLauf] = useState<SyncRun | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fragt, setFragt] = useState(false);
  const [synct, setSynct] = useState(false);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const statusLaden = useCallback(async () => {
    setFehler(null);
    try {
      // Ausschliesslich lesend. Kein requestAuthorization, kein Sync.
      const [a, s] = await Promise.all([api.getAuthorization(), api.getSyncStatus()]);
      setAuth(a);
      setStatus(s);
    } catch (e) {
      setFehler(fehlerbild(e));
    } finally {
      setLaedt(false);
    }
  }, []);

  useEffect(() => { void statusLaden(); }, [statusLaden]);

  const erlauben = async () => {
    if (fragt || synct) return;
    setFragt(true);
    setFehler(null);
    try {
      setAuth(await api.requestAuthorization());
    } catch (e) {
      setFehler(fehlerbild(e));
    } finally {
      setFragt(false);
    }
  };

  const abgleichen = async () => {
    if (synct || fragt) return;
    setSynct(true);
    setFehler(null);
    try {
      const ergebnis = await api.runSync();
      setLauf(ergebnis);
      if (ergebnis.succeeded) {
        onSynced();
        setStatus(await api.getSyncStatus());
      }
    } catch (e) {
      setFehler(fehlerbild(e));
    } finally {
      setSynct(false);
    }
  };

  if (laedt) return <LoadingState label="Berechtigung wird geprüft" />;

  const text = AUTH_TEXT[auth?.status ?? 'unknown'];
  const autorisiert = auth?.status === 'authorized';
  const letzterAbgleich = status.map((s) => s.updated_at).sort().slice(-1)[0];

  return (
    <section aria-labelledby="pj-sync-titel" style={statusKarte()}>
      <h3 id="pj-sync-titel" style={{ font: 'var(--pjc-font-title)', margin: 0 }}>
        Apple Kontakte
      </h3>
      <p data-testid="auth-status" style={{ font: 'var(--pjc-font-body)', margin: '4px 0 0' }}>
        {text.titel}
      </p>
      <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
        {text.hinweis}
      </p>
      {auth && !auth.bridge_available && (
        <div style={{ font: 'var(--pjc-font-body)', color: 'var(--color-warning)', marginTop: '6px' }}>
          <p style={{ margin: 0 }}>{auth.reason || 'Die Kontakte-Brücke ist nicht verfügbar.'}</p>
          {auth.technical_code && (
            <p data-testid="auth-kennung"
               style={{ margin: '4px 0 0', fontFamily: 'monospace', font: 'var(--pjc-font-label)' }}>
              Code: {auth.technical_code}
            </p>
          )}
        </div>
      )}
      <div style={{ display: 'flex', gap: '8px', marginTop: '10px', flexWrap: 'wrap' }}>
        {auth?.can_request && (
          <button type="button" onClick={erlauben} disabled={fragt || synct}
                  className="pjc-focusable" style={aktionsKnopf(false)}>
            {fragt && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
            {' '}Zugriff auf Kontakte erlauben
          </button>
        )}
        {autorisiert && (
          <button type="button" onClick={abgleichen} disabled={synct || fragt}
                  data-testid="sync-starten"
                  className="pjc-focusable" style={aktionsKnopf(false)}>
            {synct
              ? <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              : <RefreshCw size={13} aria-hidden="true" />}
            {' '}Kontakte synchronisieren
          </button>
        )}
      </div>
      {fragt && (
        <p role="status" style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', marginTop: '8px' }}>
          Warte auf deine Entscheidung im macOS-Dialog…
        </p>
      )}
      {synct && (
        <p role="status" style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', marginTop: '8px' }}>
          Kontakte werden gelesen…
        </p>
      )}
      {fehler && <ErrorState {...fehler} onRetry={() => void statusLaden()} />}
      {lauf && !fehler && (
        <div role="status" data-testid="sync-ergebnis"
             style={{ ...statusKarte(), marginTop: '10px' }}>
          {lauf.succeeded ? (
            <>
              <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
                {SYNC_MODUS[lauf.mode] ?? lauf.mode} abgeschlossen
              </p>
              <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
                {lauf.containers} Container · {lauf.read} gelesen · {lauf.imported} neu ·{' '}
                {lauf.updated} aktualisiert · {lauf.tombstoned} entfernt ·{' '}
                {lauf.unchanged} unverändert
              </p>
            </>
          ) : (
            <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-warning)', margin: 0 }}>
              Der Abgleich ist fehlgeschlagen
              {lauf.error_class ? ` (${lauf.error_class})` : ''}.
              {lauf.retryable && ' Ein erneuter Versuch ist sinnvoll.'}
            </p>
          )}
        </div>
      )}
      {letzterAbgleich && (
        <p style={{ font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)', marginTop: '8px' }}>
          Zuletzt abgeglichen: {new Date(letzterAbgleich).toLocaleString('de-DE')}
        </p>
      )}
    </section>
  );
}

// ── Freigaben ──────────────────────────────────────────────────────────────
function ApprovalBoard({ quelle, onOpenMutation }: {
  quelle: ContactsDataSource;
  onOpenMutation: (id: string) => void;
}) {
  const [eintraege, setEintraege] = useState<Approval[]>([]);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try { setEintraege(await quelle.listApprovals()); }
    catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, [quelle]);
  useEffect(() => { void laden(); }, [laden]);

  const handeln = async (fn: () => Promise<unknown>) => {
    try { await fn(); await laden(); } catch (e) { setFehler(fehlerbild(e)); }
  };

  if (laedt) return <LoadingState label="Freigaben werden geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (eintraege.length === 0) {
    return <EmptyState title="Keine offenen Freigaben"
                       hint="Sobald du eine Änderung vorbereitest, erscheint sie hier." />;
  }

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {eintraege.map((a) => {
        const wartet = a.state === 'awaiting_approval';
        return (
          <li key={a.approval_id} style={{
            borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
            padding: '10px 0',
          }}>
            <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
              {COMMAND_LABELS[a.command] ?? a.command}
              <button type="button" onClick={() => onOpenMutation(a.mutation_id)}
                      className="pjc-focusable"
                      style={{
                        marginLeft: '8px', border: 'none', background: 'none',
                        font: 'var(--pjc-font-body)', textDecoration: 'underline',
                        color: 'var(--color-accent)',
                      }}>
                Vorgang öffnen
              </button>
            </p>
            {/* Wohin — vor den Knöpfen. Wer hier freigibt, muss den Zielort
                gesehen haben; genau das ist die informierte Freigabe (§8 A). */}
            <div style={{ marginTop: '6px' }}>
              <Zielangabe command={a.command}
                          targetLabel={a.target_display_name}
                          containerRef={a.container_ref}
                          containerType={a.container_type}
                          containerName={a.container_name}
                          containerContactCount={a.container_contact_count} />
            </div>
            <p style={{
              font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)',
              margin: '6px 0 0', display: 'flex', flexWrap: 'wrap', gap: '8px',
            }}>
              <span>Ausgelöst von {a.actor} ({a.initiation_context})</span>
              <span>gültig bis {a.expires_at}</span>
              {a.is_expired ? <Chip tone="warn">abgelaufen</Chip> : <Chip>{a.state}</Chip>}
            </p>
            <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
              {wartet && !a.is_expired && (
                <>
                  <button type="button" data-testid="freigabe-freigeben"
                          onClick={() => void handeln(() => freigeben(a, 'lukas'))}
                          className="pjc-focusable pjc-primary"
                          style={{
                            ...aktionsKnopf(false),
                            backgroundColor: 'var(--pjc-selection-bg)',
                            color: 'var(--pjc-selection-fg)', border: 'none',
                          }}>
                    Freigeben
                  </button>
                  <button type="button"
                          onClick={() => void handeln(() => quelle.reject(a.mutation_id, 'lukas'))}
                          className="pjc-focusable" style={aktionsKnopf(false)}>
                    Ablehnen
                  </button>
                  <button type="button"
                          onClick={() => void handeln(() => quelle.cancel(a.mutation_id, 'lukas'))}
                          className="pjc-focusable" style={aktionsKnopf(false)}>
                    Abbrechen
                  </button>
                </>
              )}
              {wartet && a.is_expired && (
                <button type="button"
                        onClick={() => void handeln(() => quelle.expire(a.mutation_id))}
                        className="pjc-focusable" style={aktionsKnopf(false)}>
                  Als abgelaufen markieren
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ── Vorgänge ───────────────────────────────────────────────────────────────
/**
 * Der Stand des App-Prozess-Kanals, im Klartext.
 *
 * Bewusst **ohne** Abruf: In Phase A ist der Kanalzustand eine Konstante des
 * Kerns (`channel_mode: "disabled"`), kein Laufzeitwert. Ein Abruf brächte
 * keine zusätzliche Wahrheit, würde aber im Demo-Modus einen Endpunkt
 * anfassen — und dort ist die Zahl der Client-Aufrufe vertraglich null.
 * Ein Test hält den Satz mit der Kernkonstante deckungsgleich.
 */
/**
 * Macht einen Vorschauwert lesbar — auch die etikettierten Listen.
 *
 * `String(wert)` ergab bei ihnen `[object Object]`: Der Mensch sah vor der
 * Freigabe „emails: [object Object]" und konnte gerade das nicht prüfen,
 * was er freigeben soll. Etikett und Wert werden deshalb ausgeschrieben;
 * Anschriften als Komponentenkette in Reihenfolge.
 */
function lesbar(wert: unknown): string {
  if (wert === null || wert === undefined || wert === '') return '—';
  if (Array.isArray(wert)) return wert.map(lesbar).join(' · ');
  if (typeof wert === 'object') {
    const o = wert as Record<string, unknown>;
    const etikett = typeof o.label === 'string' && o.label ? `${o.label}: ` : '';
    if (typeof o.value === 'string') return `${etikett}${o.value}`;
    if (o.month !== undefined && o.day !== undefined) {
      const jahr = o.year ? `${o.year}-` : '--';
      const zwei = (n: unknown) => String(n).padStart(2, '0');
      return `${etikett}${jahr}${zwei(o.month)}-${zwei(o.day)}`;
    }
    // Anschrift: die gefüllten Komponenten in Vertragsreihenfolge.
    const teile = ['street', 'city', 'state', 'postalCode', 'country',
                   'isoCountryCode']
      .map((k) => o[k]).filter((v) => typeof v === 'string' && v);
    if (teile.length > 0) return `${etikett}${teile.join(', ')}`;
    return `${etikett}?`;
  }
  return String(wert);
}

function KanalHinweis({ caps }: { caps: Capabilities | null }) {
  // Der Satz folgt dem **tatsächlichen** Zustand. Er war fest verdrahtet,
  // solange der Kanal konstant geschlossen war; seit der Schreibfreigabe
  // stimmte er nicht mehr — und ein Hinweis, der das Gegenteil dessen
  // behauptet, was gleich passiert, ist schlimmer als keiner.
  const offen = Boolean(caps && (caps.create_supported || caps.update_supported
                                 || caps.delete_supported));
  const erlaubt = !caps ? [] : (
    [['create', caps.create_supported], ['update', caps.update_supported],
     ['delete', caps.delete_supported]] as const)
    .filter(([, an]) => an).map(([name]) => name);
  return (
    <section style={statusKarte(offen ? 'var(--color-warning)' : undefined)}
             aria-label="Ausführungskanal" data-testid="kanal-hinweis">
      <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
        {offen
          ? 'Provider-Schreiben ist zeitlich begrenzt freigegeben.'
          : `${api.PHASE_A_KANALTEXT}.`}
      </p>
      <p style={{
        font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)',
        margin: '4px 0 0',
      }}>
        {offen
          ? `Freigegeben: ${erlaubt.join(', ')}. Ausführen überträgt an Apple `
            + 'Kontakte — genau einmal je Freigabe.'
          : 'Vorgänge lassen sich vorbereiten und freigeben; an Apple Kontakte '
            + 'überträgt dieser Stand nichts.'}
      </p>
    </section>
  );
}

function kannAusfuehren(m: MutationDetail, caps: Capabilities | null): boolean {
  if (m.state !== 'approved') return false;
  if (m.command === 'create') return Boolean(caps?.create_supported);
  if (m.command === 'update') return Boolean(caps?.update_supported);
  return Boolean(caps?.delete_supported);
}

function MutationDetailView({ id, quelle, onBack }: {
  id: string;
  quelle: ContactsDataSource;
  onBack: () => void;
}) {
  const [m, setM] = useState<MutationDetail | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [gleichtAb, setGleichtAb] = useState(false);
  const [fuehrtAus, setFuehrtAus] = useState(false);
  const [loestAuf, setLoestAuf] = useState(false);
  const [fragtAbschluss, setFragtAbschluss] = useState(false);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  // R2: Löschen verlangt eine zweite, eigene Handlung im Ausführungsschritt
  // (ADR-0026 §8.3, DEC-053). Bewusst ein eigener Zustand und keine
  // Wiederverwendung der Freigabe — sonst wäre es dieselbe Handlung zweimal
  // gezählt.
  const [bestaetigt, setBestaetigt] = useState(false);

  useEffect(() => {
    quelle.capabilities().then(setCaps).catch(() => setCaps(null));
  }, [quelle]);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try { setM(await quelle.getMutation(id)); }
    catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, [id, quelle]);
  useEffect(() => { void laden(); }, [laden]);

  if (laedt) return <LoadingState label="Vorgang wird geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (!m) return <EmptyState title="Vorgang nicht gefunden" />;

  return (
    <div>
      <button type="button" onClick={onBack} className="pjc-focusable"
              style={{
                ...aktionsKnopf(false), border: 'none',
                display: 'inline-flex', alignItems: 'center', gap: '4px',
                color: 'var(--color-text-muted)', paddingLeft: 0,
              }}>
        <ArrowLeft size={13} aria-hidden="true" /> Zurück
      </button>

      <h3 style={{ font: 'var(--pjc-font-title)', fontSize: '1rem', margin: '8px 0 0' }}>
        {COMMAND_LABELS[m.command] ?? m.command}
        {m.target_display_name && <> · {m.target_display_name}</>}
      </h3>
      <div style={{ display: 'flex', gap: '6px', marginTop: '6px', flexWrap: 'wrap' }}>
        <StateChip state={m.state} />
        {m.last_error_code && <Chip tone="warn">{m.last_error_code}</Chip>}
        <Chip>Versuche: {m.attempt_count}</Chip>
      </div>

      {/* Der Stand des Kontingents, an der Stelle, an der es sich ändert.
          Gezählt wird beim Ausführen, nicht beim Freigeben — deshalb steht
          die Zahl hier und nicht in der Vorschau. Der Schlüssel führt
          Zustand und Versuchszahl mit: Beide ändern sich durch genau die
          Handlung, die verbraucht. */}
      <Kontingentanzeige schluessel={`${m.state}:${m.attempt_count}`} />

      {/* Wohin wirkt das? Vor Zustand und Aktion, weil es die erste Frage
          vor einer Freigabe ist und nicht die letzte (§8 A). */}
      <div style={{ marginTop: '10px' }}>
        <Zielangabe command={m.command} targetLabel={m.target_display_name}
                    containerRef={m.container_ref}
                    containerType={m.container_type}
                    containerName={m.container_name}
                    containerContactCount={m.container_contact_count} />
      </div>

      {m.state === 'approved' && (
        <div style={statusKarte()}>
          <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
            Freigegeben — noch nicht ausgeführt.
          </p>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Die Freigabe allein ändert bei Apple Kontakte nichts. Erst dieser
            Schritt überträgt den Vorgang, und er läuft genau einmal.
          </p>
          {/* Bis wann sie gilt. Ein scharfer Vorgang ohne sichtbare Frist
              laesst den Eigentuemer im Unklaren, wie lange er Zeit hat. */}
          {m.approval_expires_at && (
            <p data-testid="freigabe-frist" style={{
              font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)',
              margin: '4px 0 0',
            }}>
              Freigabe gültig bis {m.approval_expires_at}
            </p>
          )}
          <button
            type="button" data-testid="ausfuehren"
            disabled={fuehrtAus || !kannAusfuehren(m, caps)
                      || (m.command === 'delete' && !bestaetigt)}
            onClick={async () => {
              setFuehrtAus(true); setFehler(null);
              try {
                await quelle.execute(m.mutation_id,
                                     m.command === 'delete' ? bestaetigt : false);
                await laden();
              }
              catch (e) { setFehler(fehlerbild(e)); }
              setFuehrtAus(false);
            }}
            className="pjc-focusable pjc-primary"
            style={{
              ...aktionsKnopf(false), marginTop: '10px',
              backgroundColor: 'var(--pjc-selection-bg)',
              color: 'var(--pjc-selection-fg)', border: 'none',
              opacity: kannAusfuehren(m, caps) ? 1 : 0.5,
            }}
          >
            {fuehrtAus && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
            {' '}Jetzt ausführen
          </button>
          {m.command === 'delete' && (
            <label style={{
              display: 'flex', gap: '8px', alignItems: 'flex-start',
              font: 'var(--pjc-font-body)', marginTop: '10px',
            }} data-testid="delete-bestaetigung">
              <input
                type="checkbox" checked={bestaetigt}
                onChange={(e) => setBestaetigt(e.target.checked)}
                className="pjc-focusable"
              />
              <span>
                Ja, diesen Kontakt bei Apple Kontakte <strong>löschen</strong>.
                Das lässt sich nicht rückgängig machen.
              </span>
            </label>
          )}
          {/* Ein scharfer Vorgang braucht auch den Rueckweg. Ohne ihn bliebe
              nur Warten auf den Ablauf — oder Ausfuehren. */}
          <button
            type="button" data-testid="vorgang-verwerfen" disabled={fuehrtAus}
            onClick={async () => {
              setFehler(null);
              try { await quelle.cancel(m.mutation_id, 'lukas'); await laden(); }
              catch (e) { setFehler(fehlerbild(e)); }
            }}
            className="pjc-focusable"
            style={{ ...aktionsKnopf(false), marginTop: '10px' }}>
            Vorgang verwerfen
          </button>
          {!kannAusfuehren(m, caps) && (
            <p style={{ font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)', margin: '6px 0 0' }}>
              Diese Operation ist für Apple Kontakte noch nicht freigeschaltet.
            </p>
          )}
        </div>
      )}

      {m.state === 'outcome_unknown' && (
        <div role="alert" style={statusKarte('var(--color-warning)')}>
          <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
            Der Ausgang ist unbekannt.
          </p>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Die Änderung wurde möglicherweise schon ausgeführt — oder auch
            nicht. Ein zweiter Versuch könnte sie doppelt anwenden. Deshalb
            gibt es hier kein „erneut senden": Der einzige sichere Weg ist der
            Abgleich mit Apple Kontakte.
          </p>
          <button
            type="button" disabled={gleichtAb} data-testid="zustand-abgleichen"
            onClick={async () => {
              setGleichtAb(true); setFehler(null);
              try { await quelle.reconcile(m.mutation_id); await laden(); }
              catch (e) { setFehler(fehlerbild(e)); }
              finally { setGleichtAb(false); }
            }}
            className="pjc-focusable"
            style={{ ...aktionsKnopf(false), marginTop: '10px', borderColor: 'var(--color-warning)' }}
          >
            {gleichtAb
              ? <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              : <RefreshCw size={13} aria-hidden="true" />}
            {' '}Zustand abgleichen
          </button>
        </div>
      )}

      {(m.state === 'outcome_unknown' || m.state === 'manual_decision_required') && (
        <div style={statusKarte()}>
          <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
            Selbst in Apple Kontakte nachgesehen?
          </p>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Wenn du dort nachgeschaut hast und die Änderung <strong>nicht</strong>
            {' '}vorhanden ist, kannst du den Vorgang hier abschliessen. Es wird
            dabei nichts erneut übertragen.
          </p>
          {!fragtAbschluss ? (
            <button type="button" data-testid="extern-geprueft"
                    onClick={() => setFragtAbschluss(true)}
                    className="pjc-focusable"
                    style={{ ...aktionsKnopf(false), marginTop: '10px' }}>
              Extern geprüft: Änderung nicht vorhanden
            </button>
          ) : (
            <div style={statusKarte('var(--color-warning)')}>
              <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
                Du bestätigst: Die Änderung ist in Apple Kontakte nicht
                vorhanden. Der Vorgang wird endgültig geschlossen und lässt
                sich nicht erneut ausführen.
              </p>
              <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
                <button type="button" onClick={() => setFragtAbschluss(false)}
                        className="pjc-focusable" style={aktionsKnopf(false)}>
                  Abbrechen
                </button>
                <button
                  type="button" disabled={loestAuf} data-testid="abschluss-bestaetigen"
                  onClick={async () => {
                    setLoestAuf(true); setFehler(null);
                    try {
                      await quelle.resolveNotObserved(m.mutation_id);
                      setFragtAbschluss(false);
                      await laden();
                    } catch (e) { setFehler(fehlerbild(e)); }
                    setLoestAuf(false);
                  }}
                  className="pjc-focusable pjc-primary"
                  style={{
                    ...aktionsKnopf(false),
                    backgroundColor: 'var(--pjc-selection-bg)',
                    color: 'var(--pjc-selection-fg)', border: 'none',
                  }}
                >
                  {loestAuf && <Loader2 size={13} className="animate-spin" aria-hidden="true" />}
                  {' '}Ja, so abschliessen
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {m.state === 'manual_decision_required' && (
        <div role="alert" style={statusKarte('var(--color-warning)')}>
          <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
            Der Abgleich war nicht eindeutig.
          </p>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Der beobachtete Zustand passt weder eindeutig zur erwarteten
            Änderung noch eindeutig dagegen. Automatisch wird hier nichts
            entschieden.
          </p>
        </div>
      )}

      {m.state === 'manually_resolved_not_applied' && (
        <div style={statusKarte()}>
          <p style={{ font: 'var(--pjc-font-body)', fontWeight: 600, margin: 0 }}>
            Abgeschlossen: Änderung war beim Provider nicht vorhanden.
          </p>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Der technische Ausgang bleibt in der Nachweiskette als unbekannt
            stehen. Ein erneuter Versuch wäre eine neue Änderung mit eigener
            Freigabe.
          </p>
        </div>
      )}

      {m.state === 'failed_before_send' && (
        <p style={{ ...statusKarte(), font: 'var(--pjc-font-body)' }}>
          Es wurde nachweislich nichts übertragen. Der Vorgang ist damit
          abgeschlossen.
        </p>
      )}

      {m.changes.length > 0 && (
        <section style={{ marginTop: '14px' }}>
          <h4 style={{
            font: 'var(--pjc-font-section)', textTransform: 'uppercase',
            color: 'var(--color-text-muted)', margin: 0,
          }}>
            Geplante Änderung
          </h4>
          <div style={{ marginTop: '6px' }}>
            {m.changes.map((c) => (
              <p key={c.field_name} style={{ font: 'var(--pjc-font-body)', margin: '2px 0' }}>
                {c.field_name}: {lesbar(c.previous)} → <strong>{lesbar(c.planned)}</strong>
              </p>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function MutationList({ quelle, onOpen, nurAufmerksamkeit = false }: {
  quelle: ContactsDataSource;
  onOpen: (id: string) => void;
  /** Nur laufende, klemmende oder ungeklärte Vorgänge zeigen. */
  nurAufmerksamkeit?: boolean;
}) {
  const [items, setItems] = useState<Mutation[]>([]);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try {
      const alle = await quelle.listMutations();
      setItems(nurAufmerksamkeit
        ? alle.filter((m) => gehoert_in_die_vorgangsliste(m.state))
        : alle);
    } catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, [quelle, nurAufmerksamkeit]);
  useEffect(() => { void laden(); }, [laden]);

  if (laedt) return <LoadingState label="Vorgänge werden geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (items.length === 0) return <EmptyState title="Noch keine Vorgänge" />;

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((m) => (
        <li key={m.mutation_id} style={{
          borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
        }}>
          <button type="button" onClick={() => onOpen(m.mutation_id)}
                  className="pjc-focusable"
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    border: 'none', background: 'none', padding: '8px 0',
                    color: 'var(--color-text)',
                  }}>
            <span style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ font: 'var(--pjc-font-body)', fontWeight: 600 }}>
                {COMMAND_LABELS[m.command] ?? m.command}
              </span>
              {m.target_display_name && (
                <span style={{ font: 'var(--pjc-font-body)' }}>{m.target_display_name}</span>
              )}
              <StateChip state={m.state} />
            </span>
            <span style={{
              display: 'block', font: 'var(--pjc-font-label)',
              color: 'var(--color-text-muted)', marginTop: '2px',
            }}>
              {m.created_at} · {m.actor}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// ── Demo-Modus-Steuerung ───────────────────────────────────────────────────
function DemoSteuerung({ demoModus, onDemoStart, onDemoEnde }: {
  demoModus: boolean;
  onDemoStart: (anzahl: number) => void;
  onDemoEnde: () => void;
}) {
  const [fragt, setFragt] = useState(false);
  const [anzahl, setAnzahl] = useState(1000);

  return (
    <section aria-label="Demo-Modus" style={statusKarte()}>
      <h3 style={{ font: 'var(--pjc-font-title)', margin: 0 }}>Demo-Modus</h3>
      {demoModus ? (
        <>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Aktiv: Die Oberfläche zeigt ausschliesslich synthetische Kontakte.
            Es besteht keine Verbindung zum produktiven Bestand.
          </p>
          <button type="button" onClick={onDemoEnde} data-testid="demo-beenden"
                  className="pjc-focusable" style={{ ...aktionsKnopf(false), marginTop: '8px' }}>
            Demo-Modus beenden
          </button>
        </>
      ) : !fragt ? (
        <>
          <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            Zeigt die Oberfläche mit erfundenen Kontakten — ohne produktive
            Daten, ohne Sync, ohne Provider. Gilt nur für diese Sitzung.
          </p>
          <button type="button" onClick={() => setFragt(true)} data-testid="demo-anbieten"
                  className="pjc-focusable" style={{ ...aktionsKnopf(false), marginTop: '8px' }}>
            Demo-Modus vorbereiten…
          </button>
        </>
      ) : (
        <div style={{ marginTop: '8px' }}>
          <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
            Der produktive Kontaktbestand wird ausgeblendet, bis du den
            Demo-Modus beendest. Es wird nichts synchronisiert und nichts
            geschrieben.
          </p>
          <label style={{ font: 'var(--pjc-font-label)', display: 'block', marginTop: '8px' }}>
            <span style={{ color: 'var(--color-text-muted)' }}>Umfang</span>{' '}
            <select value={anzahl} onChange={(e) => setAnzahl(Number(e.target.value))}
                    data-testid="demo-anzahl"
                    className="pjc-focusable"
                    style={{
                      font: 'var(--pjc-font-body)',
                      border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                      borderRadius: 'var(--pjc-radius-control)', padding: '2px 6px',
                      background: 'transparent', color: 'var(--color-text)',
                    }}>
              <option value={100}>100 Kontakte</option>
              <option value={1000}>1.000 Kontakte</option>
              <option value={10000}>10.000 Kontakte</option>
            </select>
          </label>
          <div style={{ display: 'flex', gap: '6px', marginTop: '8px' }}>
            <button type="button" onClick={() => setFragt(false)}
                    className="pjc-focusable" style={aktionsKnopf(false)}>
              Abbrechen
            </button>
            <button type="button" data-testid="demo-starten"
                    onClick={() => { setFragt(false); onDemoStart(anzahl); }}
                    className="pjc-focusable pjc-primary"
                    style={{
                      ...aktionsKnopf(false),
                      backgroundColor: 'var(--pjc-selection-bg)',
                      color: 'var(--pjc-selection-fg)', border: 'none',
                    }}>
              Demo-Modus starten
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ── Die Fläche selbst (Einschub von rechts) ────────────────────────────────
/**
 * Zustände, die den Menschen wirklich angehen.
 *
 * „Vorgänge" war ein Dauerreiter neben „Quelle" — auch dann, wenn seit
 * Wochen nichts lief. Ein Bereich, der meistens leer ist, trainiert einem
 * ab, hinzusehen; er soll auftauchen, wenn etwas läuft, klemmt oder
 * ungeklärt ist, und sonst verschwinden. Abgeschlossene Vorgänge sind
 * Historie und gehören in die Diagnose, nicht in die Hauptansicht.
 */
const AUFMERKSAMKEIT: ReadonlySet<string> = new Set([
  // läuft
  'executing', 'provider_applied_pending_reconcile',
  // klemmt oder ist ungeklärt
  'outcome_unknown', 'reconcile_required', 'manual_decision_required',
  'failed', 'failed_before_send',
]);

/** Wartet dieser Vorgang auf eine Freigabe? */
function wartetAufFreigabe(state: string): boolean {
  return state === 'awaiting_approval';
}

export function braucht_aufmerksamkeit(state: string): boolean {
  return AUFMERKSAMKEIT.has(state);
}

/**
 * Vorgänge, die **offen und scharf** sind: vorbereitet oder freigegeben, aber
 * noch nicht ausgeführt.
 *
 * Sie fehlten bisher überall. Die Freigabeliste filtert auf
 * `awaiting_approval`, `AUFMERKSAMKEIT` kennt weder `approved` noch
 * `prepared` — ein freigegebener, nicht ausgeführter Vorgang erschien damit in
 * keiner Liste. Die Detailansicht mit „Jetzt ausführen" existierte, war aber
 * ohne bekannte `mutation_id` nicht erreichbar (§8 C).
 *
 * Bewusst getrennt von `AUFMERKSAMKEIT`: Das eine klemmt und braucht
 * Diagnose, das andere wartet auf eine Entscheidung. Beides zusammenzuwerfen
 * verlöre genau den Unterschied, auf den es ankommt.
 */
const OFFEN: ReadonlySet<string> = new Set(['prepared', 'awaiting_approval',
  'approved']);

export function ist_offen(state: string): boolean {
  return OFFEN.has(state);
}

export function gehoert_in_die_vorgangsliste(state: string): boolean {
  return braucht_aufmerksamkeit(state) || ist_offen(state);
}

type StatusTab = 'quelle' | 'vorgaenge' | 'diagnose';

export function ContactsStatusSurface({
  quelle, demoModus, onClose, onSynced, onDemoStart, onDemoEnde, startTab,
  startMutationId,
}: {
  quelle: ContactsDataSource;
  demoModus: boolean;
  onClose: () => void;
  onSynced: () => void;
  onDemoStart: (anzahl: number) => void;
  onDemoEnde: () => void;
  /** Nur für Dev-Szenarien: Starttab der Fläche. */
  startTab?: StatusTab;
  /**
   * Direkt auf diesen Vorgang aufschlagen. Gebraucht nach einer Freigabe:
   * Der Eigentuemer soll den freigegebenen Vorgang sehen und dort — als
   * **eigene** Handlung — ausfuehren, statt ihn in einer Liste suchen zu
   * muessen. Ausgefuehrt wird dadurch nichts; es wird nur angezeigt.
   */
  startMutationId?: string | null;
}) {
  const [tab, setTab] = useState<StatusTab>(
    startTab === 'diagnose' || startTab === 'vorgaenge' ? startTab : 'quelle',
  );
  const [mutationId, setMutationId] = useState<string | null>(
    startMutationId ?? null);
  // Über die Quelle, nicht über einen eigenen Abruf: Der Demo-Modus bleibt
  // damit aufruffrei (sein Nullaufruf-Vertrag), und der Hinweis zeigt
  // trotzdem den echten Stand.
  const [kanalCaps, setKanalCaps] = useState<Capabilities | null>(null);
  useEffect(() => {
    let aktiv = true;
    quelle.capabilities()
      .then((c) => { if (aktiv) setKanalCaps(c); })
      .catch(() => { if (aktiv) setKanalCaps(null); });
    return () => { aktiv = false; };
  }, [quelle]);

  // Der Bestand entscheidet über die Reiter, nicht eine feste Liste.
  const [offeneVorgaenge, setOffeneVorgaenge] = useState<Mutation[]>([]);
  useEffect(() => {
    let aktiv = true;
    quelle.listMutations()
      .then((alle) => {
        if (aktiv) {
          setOffeneVorgaenge(
            alle.filter((m) => gehoert_in_die_vorgangsliste(m.state)));
        }
      })
      .catch(() => { if (aktiv) setOffeneVorgaenge([]); });
    return () => { aktiv = false; };
  }, [quelle, mutationId]);

  // „Freigaben" ist kein Reiter mehr: Eine Freigabe gehört an den Vorgang,
  // den sie betrifft — als Dialog im Moment der Entscheidung, nicht als
  // Sammelliste, die man irgendwann durchsieht.
  const zeigeVorgaenge = offeneVorgaenge.length > 0 || mutationId !== null
    || tab === 'vorgaenge';
  const tabs: { key: StatusTab; label: string }[] = [
    { key: 'quelle', label: 'Quelle' },
    ...(zeigeVorgaenge
      ? [{ key: 'vorgaenge' as StatusTab,
           label: offeneVorgaenge.length > 0
             ? `Vorgänge (${offeneVorgaenge.length})` : 'Vorgänge' }]
      : []),
    { key: 'diagnose', label: 'Diagnose' },
  ];

  return (
    <aside
      role="complementary"
      aria-label="Vorgänge und Status"
      data-testid="status-flaeche"
      style={{
        position: 'absolute',
        top: 0, right: 0, bottom: 0,
        width: 'min(420px, 90%)',
        backgroundColor: 'var(--color-surface, var(--color-bg))',
        borderLeft: 'var(--pjc-divider-width) solid var(--pjc-divider)',
        boxShadow: 'var(--shadow-lg, 0 8px 30px rgba(0,0,0,0.25))',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 20,
      }}
    >
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        // Rechts Freiraum: dort schwebt die globale Approval-Glocke der App
        // ueber der Flaeche — das Schliessen-X muss davor enden.
        padding: 'var(--pjc-pane-pad) var(--pjc-toolbar-reserve) var(--pjc-pane-pad) var(--pjc-pane-pad)',
        borderBottom: 'var(--pjc-divider-width) solid var(--pjc-divider)',
      }}>
        <h2 style={{ font: 'var(--pjc-font-title)', margin: 0 }}>
          Vorgänge & Status
        </h2>
        <button type="button" onClick={onClose} aria-label="Statusfläche schliessen"
                data-testid="status-schliessen"
                className="pjc-focusable"
                style={{
                  border: 'none', background: 'none',
                  color: 'var(--color-text-muted)',
                  minWidth: 'var(--pjc-hit-target)', minHeight: 'var(--pjc-hit-target)',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>
          <X size={16} aria-hidden="true" />
        </button>
      </header>

      <div role="tablist" aria-label="Statusbereiche" style={{
        display: 'flex', gap: '2px', padding: '0 var(--pjc-pane-pad)',
        borderBottom: 'var(--pjc-divider-width) solid var(--pjc-divider)',
      }}>
        {tabs.map((t) => (
          <button
            key={t.key} type="button" role="tab" id={`status-tab-${t.key}`}
            aria-selected={tab === t.key} aria-controls={`status-panel-${t.key}`}
            onClick={() => { setTab(t.key); setMutationId(null); }}
            className="pjc-focusable"
            style={{
              font: 'var(--pjc-font-body)',
              border: 'none', background: 'none',
              padding: '8px 10px',
              borderBottom: `2px solid ${tab === t.key ? 'var(--color-accent)' : 'transparent'}`,
              color: tab === t.key ? 'var(--color-accent)' : 'var(--color-text-muted)',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div
        id={`status-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`status-tab-${tab}`}
        style={{ flex: 1, overflowY: 'auto', padding: 'var(--pjc-pane-pad)' }}
      >
        {tab === 'quelle' && (
          <>
            {demoModus ? (
              <section style={statusKarte()} aria-label="Quelle">
                <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
                  Demo-Modus aktiv — Quelle sind synthetische Kontakte.
                  Berechtigung und Abgleich betreffen nur den produktiven
                  Betrieb und sind hier ausgeblendet.
                </p>
              </section>
            ) : (
              <SyncPanel onSynced={onSynced} />
            )}
            <DemoSteuerung
              demoModus={demoModus}
              onDemoStart={onDemoStart}
              onDemoEnde={onDemoEnde}
            />
          </>
        )}
        {tab === 'vorgaenge' && (
          <>
            <KanalHinweis caps={kanalCaps} />
            {mutationId
              ? <MutationDetailView id={mutationId} quelle={quelle}
                                    onBack={() => setMutationId(null)} />
              : <MutationList quelle={quelle} onOpen={setMutationId}
                              nurAufmerksamkeit />}
          </>
        )}
        {tab === 'diagnose' && (
          mutationId
            ? <MutationDetailView id={mutationId} quelle={quelle}
                                  onBack={() => setMutationId(null)} />
            : (
              <>
                <p style={{
                  font: 'var(--pjc-font-label)',
                  color: 'var(--color-text-muted)', margin: '0 0 10px',
                }}>
                  Vollständige Historie aller Vorgänge und Freigaben —
                  auch der abgeschlossenen. Technischer Nachweis, kein
                  Arbeitsbereich.
                </p>
                <MutationList quelle={quelle} onOpen={setMutationId} />
                <ApprovalBoard quelle={quelle} onOpenMutation={setMutationId} />
              </>
            )
        )}
      </div>
    </aside>
  );
}

function statusKarte(rand?: string): React.CSSProperties {
  return {
    border: `var(--pjc-divider-width) solid ${rand ?? 'var(--pjc-divider)'}`,
    borderRadius: 'var(--pjc-radius-control)',
    padding: '12px',
    marginTop: '10px',
  };
}

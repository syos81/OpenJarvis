// Kontakte — Übersicht, Detail, Freigabe-Board und Mutationsstatus.
//
// Der vertikale Fluss ist bewusst durchgehend: suchen → öffnen → ändern →
// Vorschau → Freigabe → Status. Kein Schritt löst eine Provideroperation aus;
// die Ausführung ist ein getrennter Vorgang, den diese Oberfläche nicht
// anbietet.

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft, ChevronRight, Loader2, Plus, RefreshCw, Search, Trash2, X,
} from 'lucide-react';
import * as api from './api';
import { ContactsApiError } from './api';
import type {
  Approval, Authorization, AuthorizationState, Capabilities, ContactDetail,
  ContactSummary, Mutation, MutationDetail, PreparedMutation, RoleCount,
  SyncRun, SyncStatus,
} from './api';
import {
  ChangeTable, Chip, COMMAND_LABELS, EmptyState, ErrorState, FieldStateBadge,
  LoadingState, Modal, MUTATION_LABELS, StateChip, availabilityOf,
} from './components';

type Tab = 'contacts' | 'approvals' | 'mutations';

function neueId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `id-${Date.now()}-${Math.random()}`;
}

/**
 * Vollstaendiges Fehlerbild statt nur einer Zeichenkette.
 *
 * Der Server liefert Satz, Kategorie, stabile Kennung und Wiederholbarkeit
 * getrennt. Wer davon nur `message` weiterreicht, wirft genau die Angaben
 * weg, die der Nutzer braucht — und landet im schlimmsten Fall bei einem
 * nackten Ausnahmeklassennamen auf dem Bildschirm.
 */
export interface Fehlerbild {
  message: string;
  code?: string;
  technicalCode?: string;
  retryable?: boolean;
}

function fehlerbild(e: unknown): Fehlerbild {
  if (e instanceof ContactsApiError) {
    return {
      message: e.message,
      code: e.code,
      technicalCode: e.technicalCode,
      retryable: e.retryable,
    };
  }
  if (e instanceof Error) {
    // Netzwerkabbruch o. ae.: der Server hat nie geantwortet.
    return {
      message: 'Der lokale Server war nicht erreichbar.',
      technicalCode: 'network_unreachable',
      retryable: true,
    };
  }
  return { message: 'Unbekannter Fehler.', technicalCode: 'unknown' };
}

// ═══ Berechtigung und manueller Abgleich ════════════════════════════════════
//
// Diese Fläche ist der einzige Ort, von dem aus überhaupt eine Live-Operation
// gegen Apple Kontakte ausgelöst werden kann — und immer nur durch einen
// bewussten Klick. Beim Öffnen der Seite wird ausschliesslich der Status
// **gelesen**; ein Systemdialog erscheint nie von selbst.

const AUTH_TEXT: Record<AuthorizationState, { titel: string; hinweis: string }> = {
  notDetermined: {
    titel: 'Noch nicht entschieden',
    hinweis: 'Personal Jarvis hat noch nie auf deine Kontakte zugegriffen. '
      + 'Du entscheidest gleich selbst im macOS-Dialog.',
  },
  authorized: {
    titel: 'Zugriff erlaubt',
    hinweis: 'Kontakte können gelesen werden. Geändert wird nichts — '
      + 'diese Version liest ausschliesslich.',
  },
  denied: {
    titel: 'Zugriff abgelehnt',
    hinweis: 'Du hast den Zugriff abgelehnt. Ändern lässt sich das nur in den '
      + 'Systemeinstellungen unter Datenschutz & Sicherheit → Kontakte.',
  },
  restricted: {
    titel: 'Zugriff eingeschränkt',
    hinweis: 'Der Zugriff ist auf diesem Mac durch eine Richtlinie gesperrt. '
      + 'Eine Anfrage würde daran nichts ändern.',
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

// Anzeigetexte fuer maskierte Providerangaben und den geschlossenen
// Labelvorrat des Feldvertrags v1.
const ANBIETER_LABELS: Record<string, string> = {
  apple_contacts: 'Apple Kontakte',
  unknown: 'Unbekannte Quelle',
};

// Art des Ablageorts, fachlich benannt. Sie ist die Angabe, an der sich ein
// Ziel bewusst waehlen laesst — nicht Reihenfolge und nicht Groesse.
const CONTAINER_ART: Record<string, string> = {
  local: 'Lokal · Auf meinem Mac',
  cardDAV: 'CardDAV / iCloud',
  exchange: 'Exchange',
  unassigned: 'Ohne Zuordnung',
  unknown: 'Art noch nicht bekannt',
};

const LABEL_TEXT: Record<string, string> = {
  home: 'Privat', work: 'Arbeit', mobile: 'Mobil', main: 'Haupt',
  other: 'Sonstige',
};

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
      // Ausschliesslich lesend. Kein `requestAuthorization`, kein Sync.
      const [a, s] = await Promise.all([
        api.getAuthorization(), api.getSyncStatus(),
      ]);
      setAuth(a);
      setStatus(s);
    } catch (e) {
      setFehler(fehlerbild(e));
    } finally {
      setLaedt(false);
    }
  }, []);

  useEffect(() => { void statusLaden(); }, [statusLaden]);

  // Doppelklickschutz: solange eine Anfrage läuft, ist der Knopf deaktiviert
  // **und** der Handler kehrt sofort zurück. Ein zweiter Dialog oder ein
  // zweiter Lauf entstünde sonst allein durch schnelles Klicken.
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
  const letzterAbgleich = status
    .map((s) => s.updated_at)
    .sort()
    .slice(-1)[0];

  return (
    <section
      className="mb-5 rounded-md border p-4"
      style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
      aria-labelledby="pj-sync-titel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex-1" style={{ minWidth: '18rem' }}>
          <h2 id="pj-sync-titel" className="text-sm font-medium">
            Apple Kontakte
          </h2>
          <p className="mt-0.5 text-sm" data-testid="auth-status">
            {text.titel}
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            {text.hinweis}
          </p>
          {auth && !auth.bridge_available && (
            <div className="mt-1 text-sm" style={{ color: 'var(--color-warning, #b45309)' }}>
              <p>{auth.reason || 'Die Kontakte-Brücke ist nicht verfügbar.'}</p>
              {auth.technical_code && (
                <p className="mt-1 font-mono text-xs" data-testid="auth-kennung">
                  Code: {auth.technical_code}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {auth?.can_request && (
            <button
              type="button" onClick={erlauben} disabled={fragt || synct}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
              style={{ borderColor: 'var(--color-accent)', color: 'var(--color-accent)' }}
            >
              {fragt && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
              Zugriff auf Kontakte erlauben
            </button>
          )}
          {autorisiert && (
            <button
              type="button" onClick={abgleichen} disabled={synct || fragt}
              className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
              style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
            >
              {synct
                ? <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                : <RefreshCw size={14} aria-hidden="true" />}
              Kontakte synchronisieren
            </button>
          )}
        </div>
      </div>

      {fragt && (
        <p className="mt-3 text-sm" role="status" style={{ color: 'var(--color-text-muted)' }}>
          Warte auf deine Entscheidung im macOS-Dialog…
        </p>
      )}
      {synct && (
        <p className="mt-3 text-sm" role="status" style={{ color: 'var(--color-text-muted)' }}>
          Kontakte werden gelesen…
        </p>
      )}

      {fehler && <ErrorState {...fehler} onRetry={() => void statusLaden()} />}

      {lauf && !fehler && (
        <div className="mt-3 rounded-md border p-3 text-sm" data-testid="sync-ergebnis"
             style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}
             role="status">
          {lauf.succeeded ? (
            <>
              <p className="font-medium">
                {SYNC_MODUS[lauf.mode] ?? lauf.mode} abgeschlossen
              </p>
              <p className="mt-1" style={{ color: 'var(--color-text-muted)' }}>
                {lauf.containers} Container · {lauf.read} gelesen ·{' '}
                {lauf.imported} neu · {lauf.updated} aktualisiert ·{' '}
                {lauf.tombstoned} entfernt · {lauf.unchanged} unverändert
              </p>
              {lauf.requires_full_diff && (
                <p className="mt-1" style={{ color: 'var(--color-warning, #b45309)' }}>
                  Beim nächsten Mal ist ein Vollabgleich nötig.
                </p>
              )}
            </>
          ) : (
            <p style={{ color: 'var(--color-warning, #b45309)' }}>
              Der Abgleich ist fehlgeschlagen
              {lauf.error_class ? ` (${lauf.error_class})` : ''}.
              {lauf.retryable && ' Ein erneuter Versuch ist sinnvoll.'}
            </p>
          )}
        </div>
      )}

      {letzterAbgleich && (
        <p className="mt-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          Zuletzt abgeglichen: {new Date(letzterAbgleich).toLocaleString('de-DE')}
        </p>
      )}
    </section>
  );
}

// ═══ Übersicht ══════════════════════════════════════════════════════════════
function ContactList({ onOpen, onCreate, reloadKey = 0 }: {
  onOpen: (id: string) => void; onCreate: () => void; reloadKey?: number;
}) {
  const [items, setItems] = useState<ContactSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [suche, setSuche] = useState('');
  const [rolle, setRolle] = useState<string | null>(null);
  const [kategorien, setKategorien] = useState<RoleCount[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const laden = useCallback(async (anhaengen = false, c?: string | null) => {
    setLaedt(true);
    setFehler(null);
    try {
      const seite = await api.listContacts({
        search: suche || undefined,
        role: rolle ?? undefined,
        cursor: anhaengen ? (c ?? undefined) : undefined,
      });
      setItems((alt) => (anhaengen ? [...alt, ...seite.items] : seite.items));
      setCursor(seite.next_cursor);
      setHasMore(seite.has_more);
    } catch (e) {
      setFehler(fehlerbild(e));
    } finally {
      setLaedt(false);
    }
  }, [suche, rolle]);

  // `reloadKey` ist die Nachladeschleuse nach einem erfolgreichen Abgleich:
  // die Liste zeigt sonst weiter den Stand von vor dem Import.
  useEffect(() => { void laden(false); }, [laden, reloadKey]);
  useEffect(() => {
    api.listCategories().then(setKategorien).catch(() => setKategorien([]));
  }, [reloadKey]);
  // Fail-closed: solange die Capabilities unbekannt sind, gilt "nicht
  // verfuegbar". Ein Knopf, der eine nicht implementierte Operation
  // verspricht, ist schlimmer als gar keiner.
  useEffect(() => { api.getCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative flex-1" style={{ minWidth: '16rem' }}>
          <Search
            size={15} aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2"
            style={{ color: 'var(--color-text-muted)' }}
          />
          <input
            type="search"
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder="Name, Organisation, E-Mail oder Nummer"
            aria-label="Kontakte durchsuchen"
            className="w-full rounded-md border py-1.5 pl-8 pr-3 text-sm"
            style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
          />
        </div>
        {/* Produktive Provider-Mutationen sind in dieser Phase geschlossen:
            der Sidecar antwortet auf create/update/delete mit
            `not_implemented`. Ein sichtbarer, klickbarer "Kontakt anlegen"
            waere daher ein Versprechen, das das System nicht halten kann.
            Der Knopf erscheint erst, wenn der Server die Faehigkeit
            tatsaechlich meldet. */}
        {caps?.create_supported && (
          <button
            type="button" onClick={onCreate}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
            style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
          >
            <Plus size={15} aria-hidden="true" /> Kontakt anlegen
          </button>
        )}
      </div>

      {kategorien.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5" role="group" aria-label="Nach Kategorie filtern">
          <button
            type="button" onClick={() => setRolle(null)} aria-pressed={rolle === null}
            className="rounded-full border px-2.5 py-0.5 text-xs"
            style={{
              borderColor: rolle === null ? 'var(--color-accent)' : 'var(--color-border, rgba(127,127,127,0.3))',
              color: rolle === null ? 'var(--color-accent)' : undefined,
            }}
          >
            Alle
          </button>
          {kategorien.map((k) => (
            <button
              key={k.role} type="button" aria-pressed={rolle === k.role}
              onClick={() => setRolle(rolle === k.role ? null : k.role)}
              className="rounded-full border px-2.5 py-0.5 text-xs"
              style={{
                borderColor: rolle === k.role ? 'var(--color-accent)' : 'var(--color-border, rgba(127,127,127,0.3))',
                color: rolle === k.role ? 'var(--color-accent)' : undefined,
              }}
            >
              {k.role} ({k.count})
            </button>
          ))}
        </div>
      )}

      {fehler && <ErrorState {...fehler} onRetry={() => void laden(false)} />}
      {laedt && items.length === 0 && <LoadingState label="Kontakte werden geladen" />}

      {!laedt && !fehler && items.length === 0 && (
        <EmptyState
          title="Keine Kontakte gefunden"
          hint={suche || rolle
            ? 'Suche oder Filter liefern kein Ergebnis.'
            : 'Es ist noch kein Kontakt synchronisiert. Der erste Import läuft über die Kontakte-Bridge.'}
        />
      )}

      {items.length > 0 && (
        <ul className="divide-y" style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}>
          {items.map((k) => (
            <li key={k.id}>
              <button
                type="button" onClick={() => onOpen(k.id)}
                className="flex w-full items-center gap-3 py-2.5 text-left"
              >
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="truncate font-medium">{k.display_name}</span>
                    {k.is_me_card && <Chip tone="info" title="Diese Karte gehört dir. Sie ist schreibgeschützt.">Meine Karte</Chip>}
                    {k.conflict_state && <Chip tone="warn">Konflikt</Chip>}
                    {k.field_completeness === 'partial' && <Chip tone="warn">unvollständig</Chip>}
                    {k.has_unavailable_fields && <Chip title="Mindestens ein Feld ist nicht lesbar.">nicht lesbare Felder</Chip>}
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-2 text-xs"
                        style={{ color: 'var(--color-text-muted)' }}>
                    {k.organization_name && <span className="truncate">{k.organization_name}</span>}
                    <span>{k.email_count} E-Mail · {k.phone_count} Telefon · {k.address_count} Adresse</span>
                    {/* Bewusst ohne Kontokennung: `apple-local` ist ein
                        Provider-Identifier und hat in der Oberfläche nichts
                        verloren. Die Anzahl sagt dem Nutzer alles, was ihn
                        betrifft — nämlich ob ein Kontakt aus mehreren Quellen
                        stammt. */}
                    {k.account_refs.length > 1 && (
                      <span>aus {k.account_refs.length} Quellen</span>
                    )}
                    {k.roles.map((r) => <Chip key={r}>{r}</Chip>)}
                  </span>
                </span>
                <ChevronRight size={16} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {hasMore && (
        <div className="mt-4 text-center">
          <button
            type="button" disabled={laedt}
            onClick={() => void laden(true, cursor)}
            className="rounded-md border px-3 py-1.5 text-sm"
            style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
          >
            {laedt ? 'Wird geladen…' : 'Weitere laden'}
          </button>
        </div>
      )}
    </div>
  );
}

// ═══ Detail ═════════════════════════════════════════════════════════════════
function Werteliste({ titel, werte }: {
  titel: string; werte: { id: string; label_normalized: string | null; value: string | null }[];
}) {
  if (werte.length === 0) return null;
  return (
    <section className="mt-4">
      <h3 className="text-xs font-medium uppercase tracking-wide"
          style={{ color: 'var(--color-text-muted)' }}>{titel}</h3>
      <ul className="mt-1 space-y-0.5 text-sm">
        {werte.map((w) => (
          <li key={w.id} className="flex gap-2">
            {w.label_normalized && (
              <span className="shrink-0" style={{ color: 'var(--color-text-muted)' }}>
                {w.label_normalized}
              </span>
            )}
            <span className="break-all">{w.value ?? '—'}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function ContactDetailView({ id, onBack, onPrepared }: {
  id: string; onBack: () => void; onPrepared: (m: PreparedMutation) => void;
}) {
  const [kontakt, setKontakt] = useState<ContactDetail | null>(null);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [neueRolle, setNeueRolle] = useState('');
  const [bearbeiten, setBearbeiten] = useState(false);
  const [loeschen, setLoeschen] = useState(false);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try {
      setKontakt(await api.getContact(id));
    } catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, [id]);

  useEffect(() => { void laden(); }, [laden]);
  useEffect(() => { api.getCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);

  const notizZustand = kontakt ? availabilityOf(kontakt.field_availability, 'note') : null;

  if (laedt) return <LoadingState label="Kontakt wird geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (!kontakt) return <EmptyState title="Kontakt nicht gefunden" />;

  // Drei Bedingungen, alle notwendig: die Karte darf beschreibbar sein, das
  // Backend muss ein eindeutiges Ziel aufloesen koennen (`writable`), und der
  // Provider muss die Operation ueberhaupt koennen. Seit ADR-0019 kennt die
  // Oberflaeche kein Schreibziel mehr — sie zielt ueber die lokale `id`.
  const aenderbar = !kontakt.is_me_card && kontakt.writable
    && Boolean(caps?.update_supported);
  const loeschbar = !kontakt.is_me_card && kontakt.writable
    && Boolean(caps?.delete_supported);

  return (
    <div>
      <button type="button" onClick={onBack}
              className="mb-3 inline-flex items-center gap-1 text-sm"
              style={{ color: 'var(--color-text-muted)' }}>
        <ArrowLeft size={14} aria-hidden="true" /> Zurück zur Übersicht
      </button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{kontakt.display_name}</h2>
          <p className="mt-0.5 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            {[kontakt.job_title, kontakt.department_name, kontakt.organization_name]
              .filter(Boolean).join(' · ') || 'Ohne Organisation'}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {kontakt.is_me_card && (
              <Chip tone="info" title="Die eigene Karte ist in dieser Version schreibgeschützt.">
                Meine Karte · schreibgeschützt
              </Chip>
            )}
            {kontakt.unified_read_only && (
              <Chip title="Verknüpfte Karten werden nur gelesen. Geschrieben wird immer der Rohdatensatz.">
                verknüpfte Ansicht nur lesend
              </Chip>
            )}
            {kontakt.conflict_state && <Chip tone="warn">Konflikt: {kontakt.conflict_state}</Chip>}
            {/* Kein Provider-Identifier in der Oberfläche. Dass ein Kontakt
                aus mehreren Konten stammt, ist die einzige Aussage, die den
                Nutzer hier betrifft. */}
            {kontakt.account_refs.length > 1 && (
              <Chip title="Dieser Kontakt stammt aus mehreren Konten.">
                {kontakt.account_refs.length} Quellen
              </Chip>
            )}
          </div>
        </div>
        {(aenderbar || loeschbar) && (
          <div className="flex gap-2">
            {aenderbar && (
              <button type="button" onClick={() => setBearbeiten(true)}
                      className="rounded-md border px-3 py-1.5 text-sm"
                      style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
                Ändern
              </button>
            )}
            {loeschbar && (
              <button type="button" onClick={() => setLoeschen(true)}
                      className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
                      style={{ borderColor: 'var(--color-danger, #b91c1c)', color: 'var(--color-danger, #b91c1c)' }}>
                <Trash2 size={14} aria-hidden="true" /> Löschen
              </button>
            )}
          </div>
        )}
      </div>

      {!kontakt.is_me_card && !caps?.mutations_available && (
        <p className="mt-3 rounded-md border p-3 text-sm" data-testid="mutationen-gesperrt"
           style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))',
                    color: 'var(--color-text-muted)' }}>
          Diese Version liest Kontakte ausschliesslich. Ändern und Löschen sind
          noch nicht freigeschaltet und werden deshalb nicht angeboten.
        </p>
      )}

      {kontakt.is_me_card && (
        <p className="mt-3 rounded-md border p-3 text-sm"
           style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))',
                    color: 'var(--color-text-muted)' }}>
          Die eigene Karte wird in dieser Version nicht verändert. Es gibt
          deshalb keine Schaltfläche zum Ändern oder Löschen.
        </p>
      )}

      <Werteliste titel="E-Mail" werte={kontakt.emails} />
      <Werteliste titel="Telefon" werte={kontakt.phones} />
      <Werteliste titel="Web" werte={kontakt.urls} />

      {kontakt.postal_addresses.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs font-medium uppercase tracking-wide"
              style={{ color: 'var(--color-text-muted)' }}>Adresse</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {kontakt.postal_addresses.map((a) => (
              <li key={a.id}>
                {[a.extra.street, a.extra.postal_code, a.extra.city, a.extra.country]
                  .filter(Boolean).join(', ') || '—'}
              </li>
            ))}
          </ul>
        </section>
      )}

      {kontakt.relations.length > 0 && (
        <section className="mt-4">
          <h3 className="text-xs font-medium uppercase tracking-wide"
              style={{ color: 'var(--color-text-muted)' }}>Beziehungen</h3>
          <ul className="mt-1 space-y-0.5 text-sm">
            {kontakt.relations.map((r) => (
              <li key={r.id}>
                {String(r.extra.relation_type ?? 'Beziehung')}:{' '}
                {String(r.extra.target_name_raw ?? '—')}
                {!r.extra.to_contact_id && (
                  <span className="ml-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    (nicht zugeordnet)
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Notizen: nur zeigen, wenn wirklich lesbar. */}
      <section className="mt-4">
        <h3 className="text-xs font-medium uppercase tracking-wide"
            style={{ color: 'var(--color-text-muted)' }}>Notiz</h3>
        <p className="mt-1 flex items-center gap-2 text-sm">
          {notizZustand === 'unavailable_by_capability' ? (
            <>
              <FieldStateBadge state="unavailable_by_capability" />
              <span style={{ color: 'var(--color-text-muted)' }}>
                Notizen benötigen eine besondere Apple-Berechtigung, die dieses
                Programm nicht hat. Ob eine Notiz vorhanden ist, lässt sich
                nicht feststellen — sie wird auch nie überschrieben.
              </span>
            </>
          ) : notizZustand === 'absent' ? (
            <FieldStateBadge state="absent" />
          ) : (
            <span style={{ color: 'var(--color-text-muted)' }}>—</span>
          )}
        </p>
      </section>

      {/* Lokale Kategorien */}
      <section className="mt-6">
        <h3 className="text-xs font-medium uppercase tracking-wide"
            style={{ color: 'var(--color-text-muted)' }}>
          Kategorien (nur lokal)
        </h3>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {kontakt.roles.map((r) => (
            <span key={r}
                  className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
              {r}
              <button type="button" aria-label={`Kategorie ${r} entfernen`}
                      onClick={async () => {
                        try {
                          const neu = await api.removeRole(kontakt.id, r);
                          setKontakt({ ...kontakt, roles: neu.roles });
                        } catch (e) { setFehler(fehlerbild(e)); }
                      }}>
                <X size={11} aria-hidden="true" />
              </button>
            </span>
          ))}
          <form
            className="flex items-center gap-1"
            onSubmit={async (e) => {
              e.preventDefault();
              if (!neueRolle.trim()) return;
              try {
                const neu = await api.assignRole(kontakt.id, neueRolle.trim());
                setKontakt({ ...kontakt, roles: neu.roles });
                setNeueRolle('');
              } catch (err) { setFehler(fehlerbild(err)); }
            }}
          >
            <input
              value={neueRolle} onChange={(e) => setNeueRolle(e.target.value)}
              placeholder="Privat, Arbeit, HV, Mieter, Vermieter…"
              aria-label="Neue Kategorie"
              className="rounded-md border px-2 py-0.5 text-xs"
              style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))', minWidth: '14rem' }}
            />
            <button type="submit" className="rounded-md border px-2 py-0.5 text-xs"
                    style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
              Hinzufügen
            </button>
          </form>
        </div>
        <p className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
          Kategorien bleiben auf diesem Mac. Sie werden nicht zu Apple Kontakte übertragen.
        </p>
      </section>

      {bearbeiten && (
        <UpdateDialog
          kontakt={kontakt} caps={caps}
          onClose={() => setBearbeiten(false)}
          onPrepared={(m) => { setBearbeiten(false); onPrepared(m); }}
        />
      )}
      {loeschen && (
        <DeleteDialog
          kontakt={kontakt} caps={caps}
          onClose={() => setLoeschen(false)}
          onPrepared={(m) => { setLoeschen(false); onPrepared(m); }}
        />
      )}
    </div>
  );
}

// ═══ Dialoge für Create / Update / Delete ═══════════════════════════════════
const PATCHBARE_FELDER = [
  { key: 'given_name', label: 'Vorname' },
  { key: 'family_name', label: 'Nachname' },
  { key: 'nickname', label: 'Spitzname' },
  { key: 'organization_name', label: 'Organisation' },
  { key: 'department_name', label: 'Abteilung' },
  { key: 'job_title', label: 'Position' },
];

function CapabilityHinweis({ caps }: { caps: Capabilities | null }) {
  if (!caps || caps.mutations_available) return null;
  return (
    <p className="mb-3 rounded-md border p-3 text-sm"
       style={{ borderColor: 'var(--color-warning, #b45309)' }}>
      Änderungen an Apple Kontakte sind noch nicht freigeschaltet. Der Vorgang
      wird vorbereitet und lässt sich freigeben, aber noch nicht ausführen.
    </p>
  );
}

function UpdateDialog({ kontakt, caps, onClose, onPrepared }: {
  kontakt: ContactDetail; caps: Capabilities | null;
  onClose: () => void; onPrepared: (m: PreparedMutation) => void;
}) {
  const start = useMemo(() => {
    const w: Record<string, string> = {};
    for (const f of PATCHBARE_FELDER) {
      w[f.key] = (kontakt as unknown as Record<string, string | null>)[f.key] ?? '';
    }
    return w;
  }, [kontakt]);
  const [werte, setWerte] = useState<Record<string, string>>(start);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [sendet, setSendet] = useState(false);

  const geaendert = useMemo(() => {
    const d: Record<string, string> = {};
    for (const [k, v] of Object.entries(werte)) if (v !== start[k]) d[k] = v;
    return d;
  }, [werte, start]);

  const absenden = async () => {
    setSendet(true); setFehler(null);
    try {
      onPrepared(await api.prepareUpdate(kontakt.id, {
        idempotencyKey: neueId(),
        correlationId: neueId(),
        expectedRevision: kontakt.revision,
        fields: geaendert,
      }));
    } catch (e) { setFehler(fehlerbild(e)); } finally { setSendet(false); }
  };

  return (
    <Modal
      open onClose={onClose} title="Kontakt ändern"
      description="Es werden nur die Felder übertragen, die du tatsächlich änderst. Die Änderung wird vorbereitet und braucht danach deine Freigabe."
      footer={
        <>
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-1.5 text-sm"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            Abbrechen
          </button>
          <button type="button" onClick={absenden}
                  disabled={sendet || Object.keys(geaendert).length === 0}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff', opacity: Object.keys(geaendert).length === 0 ? 0.5 : 1 }}>
            {sendet && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Änderung vorbereiten
          </button>
        </>
      }
    >
      <CapabilityHinweis caps={caps} />
      {fehler && <ErrorState {...fehler} />}
      <div className="grid gap-3 sm:grid-cols-2">
        {PATCHBARE_FELDER.map((f) => (
          <label key={f.key} className="text-sm">
            <span className="block" style={{ color: 'var(--color-text-muted)' }}>{f.label}</span>
            <input
              value={werte[f.key] ?? ''}
              onChange={(e) => setWerte({ ...werte, [f.key]: e.target.value })}
              className="mt-1 w-full rounded-md border px-2 py-1"
              style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
            />
          </label>
        ))}
      </div>
      <p className="mt-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
        Erwartete Version: {kontakt.local_revision}. Hat sich der Kontakt
        zwischenzeitlich geändert, wird der Vorgang abgelehnt statt zu
        überschreiben.
      </p>
    </Modal>
  );
}

function DeleteDialog({ kontakt, caps, onClose, onPrepared }: {
  kontakt: ContactDetail; caps: Capabilities | null;
  onClose: () => void; onPrepared: (m: PreparedMutation) => void;
}) {
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [sendet, setSendet] = useState(false);

  const absenden = async () => {
    setSendet(true); setFehler(null);
    try {
      onPrepared(await api.prepareDelete(kontakt.id, {
        idempotencyKey: neueId(),
        correlationId: neueId(),
        expectedRevision: kontakt.revision,
      }));
    } catch (e) { setFehler(fehlerbild(e)); } finally { setSendet(false); }
  };

  return (
    <Modal
      open onClose={onClose} title="Kontakt löschen"
      description="Das Löschen wird vorbereitet und braucht danach deine Freigabe."
      footer={
        <>
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-1.5 text-sm"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            Abbrechen
          </button>
          <button type="button" onClick={absenden} disabled={sendet}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
                  style={{ backgroundColor: 'var(--color-danger, #b91c1c)', color: '#fff' }}>
            {sendet && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Löschen vorbereiten
          </button>
        </>
      }
    >
      <CapabilityHinweis caps={caps} />
      {fehler && <ErrorState {...fehler} />}
      <p className="text-sm">
        Zielkontakt: <strong>{kontakt.display_name}</strong>
      </p>
      <p className="mt-2 text-sm" style={{ color: 'var(--color-danger, #b91c1c)' }}>
        Nach der Freigabe wird der Datensatz bei Apple Kontakte gelöscht. Das
        lässt sich von hier aus nicht rückgängig machen.
      </p>
      <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
        Das Ziel wird über seine feste Kennung angesprochen, nicht über den
        Namen — es kann kein anderer Kontakt getroffen werden.
      </p>
    </Modal>
  );
}

// Felder der Neuanlage nach Feldvertrag v1. Die Liste ist bewusst geschlossen
// und spiegelt `application.field_contract`: was hier nicht steht, nimmt das
// Backend auch nicht an.
const ANLAGE_FELDER = [
  { key: 'given_name', label: 'Vorname' },
  { key: 'family_name', label: 'Nachname' },
  { key: 'nickname', label: 'Spitzname' },
  { key: 'organization_name', label: 'Organisation' },
  { key: 'department_name', label: 'Abteilung' },
  { key: 'job_title', label: 'Position' },
] as const;

const MAIL_LABELS = ['home', 'work', 'other'] as const;
const TEL_LABELS = ['home', 'work', 'mobile', 'main', 'other'] as const;

function CreateDialog({ onClose, onPrepared }: {
  onClose: () => void; onPrepared: (m: PreparedMutation) => void;
}) {
  const [werte, setWerte] = useState<Record<string, string>>({});
  const [orte, setOrte] = useState<api.ContainerOption[]>([]);
  const [ort, setOrt] = useState('');
  const [mail, setMail] = useState('');
  const [mailLabel, setMailLabel] = useState<string>('home');
  const [tel, setTel] = useState('');
  const [telLabel, setTelLabel] = useState<string>('mobile');
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [sendet, setSendet] = useState(false);

  useEffect(() => { api.getCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);
  useEffect(() => {
    api.listContainers()
      // Vorausgewählt wird nur, wenn es genau einen Ablageort gibt **und**
      // seine Art erhoben ist. Ein `unknown` bleibt eine bewusste Entscheidung
      // des Nutzers — vorausgewählt sähe es aus wie eine getroffene Wahl.
      .then((o) => {
        setOrte(o);
        if (o.length === 1 && o[0].container_type !== 'unknown') {
          setOrt(o[0].container_ref);
        }
      })
      .catch(() => setOrte([]));
  }, []);

  const gefuellt = Object.entries(werte).filter(([, v]) => v.trim() !== '');
  const vollstaendig = (gefuellt.length > 0 || mail.trim() !== '' || tel.trim() !== '')
    && ort !== '' && Boolean(caps?.create_supported);

  const absenden = async () => {
    setSendet(true); setFehler(null);
    try {
      const felder: api.ContactFieldsIn = Object.fromEntries(
        gefuellt.map(([k, v]) => [k, v.trim()]),
      );
      if (mail.trim()) felder.emails = [{ label: mailLabel, value: mail.trim() }];
      if (tel.trim()) felder.phones = [{ label: telLabel, value: tel.trim() }];
      onPrepared(await api.prepareCreate({
        idempotencyKey: neueId(),
        correlationId: neueId(),
        containerRef: ort,
        fields: felder,
      }));
    } catch (e) { setFehler(fehlerbild(e)); } finally { setSendet(false); }
  };

  return (
    <Modal
      open onClose={onClose} title="Kontakt anlegen"
      description="Der Kontakt wird vorbereitet und braucht danach deine Freigabe. Ausgeführt wird er erst in einem eigenen, dritten Schritt."
      footer={
        <>
          <button type="button" onClick={onClose} className="rounded-md border px-3 py-1.5 text-sm"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            Abbrechen
          </button>
          <button type="button" onClick={absenden} disabled={sendet || !vollstaendig}
                  data-testid="anlage-vorbereiten"
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
                  style={{
                    backgroundColor: 'var(--color-accent)', color: '#fff',
                    opacity: vollstaendig ? 1 : 0.5,
                  }}>
            {sendet && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Anlage vorbereiten
          </button>
        </>
      }
    >
      <CapabilityHinweis caps={caps} />
      {fehler && <ErrorState {...fehler} />}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm sm:col-span-2">
          <span className="block" style={{ color: 'var(--color-text-muted)' }}>Ablageort</span>
          <select value={ort} onChange={(e) => setOrt(e.target.value)}
                  data-testid="anlage-ablageort"
                  className="mt-1 w-full rounded-md border px-2 py-1"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            <option value="">Bitte wählen</option>
            {orte.map((o) => (
              <option key={o.container_ref} value={o.container_ref}>
                {CONTAINER_ART[o.container_type] ?? o.container_type}
                {' · '}{ANBIETER_LABELS[o.provider_type] ?? o.provider_type}
                {' · '}{o.container_ref}
              </option>
            ))}
          </select>
          {orte.length === 0 && (
            <span className="mt-1 block text-xs" style={{ color: 'var(--color-text-muted)' }}>
              Noch kein Ablageort bekannt. Er entsteht mit der ersten Synchronisation.
            </span>
          )}
          {orte.some((o) => o.container_type === 'unknown') && (
            <span className="mt-1 block text-xs" style={{ color: 'var(--color-text-muted)' }}>
              Für manche Ablageorte ist die Art noch nicht erhoben. Ein
              Abgleich holt sie nach — bis dahin lässt sich nicht bewusst
              wählen.
            </span>
          )}
        </label>
        {ANLAGE_FELDER.map((f) => (
          <label key={f.key} className="text-sm">
            <span className="block" style={{ color: 'var(--color-text-muted)' }}>{f.label}</span>
            <input value={werte[f.key] ?? ''}
                   onChange={(e) => setWerte({ ...werte, [f.key]: e.target.value })}
                   className="mt-1 w-full rounded-md border px-2 py-1"
                   style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }} />
          </label>
        ))}
        <label className="text-sm">
          <span className="block" style={{ color: 'var(--color-text-muted)' }}>E-Mail</span>
          <div className="mt-1 flex gap-1">
            <select value={mailLabel} onChange={(e) => setMailLabel(e.target.value)}
                    aria-label="Art der E-Mail-Adresse"
                    className="rounded-md border px-2 py-1"
                    style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
              {MAIL_LABELS.map((l) => <option key={l} value={l}>{LABEL_TEXT[l]}</option>)}
            </select>
            <input value={mail} onChange={(e) => setMail(e.target.value)}
                   className="w-full rounded-md border px-2 py-1"
                   style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }} />
          </div>
        </label>
        <label className="text-sm">
          <span className="block" style={{ color: 'var(--color-text-muted)' }}>Telefon</span>
          <div className="mt-1 flex gap-1">
            <select value={telLabel} onChange={(e) => setTelLabel(e.target.value)}
                    aria-label="Art der Telefonnummer"
                    className="rounded-md border px-2 py-1"
                    style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
              {TEL_LABELS.map((l) => <option key={l} value={l}>{LABEL_TEXT[l]}</option>)}
            </select>
            <input value={tel} onChange={(e) => setTel(e.target.value)}
                   className="w-full rounded-md border px-2 py-1"
                   style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }} />
          </div>
        </label>
      </div>
    </Modal>
  );
}

function PreviewDialog({ vorgang, onClose, onEntschieden }: {
  vorgang: PreparedMutation; onClose: () => void; onEntschieden: () => void;
}) {
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  const entscheiden = async (fn: () => Promise<unknown>) => {
    setLaeuft(true); setFehler(null);
    try { await fn(); onEntschieden(); }
    catch (e) { setFehler(fehlerbild(e)); }
    finally { setLaeuft(false); }
  };

  return (
    <Modal
      open onClose={onClose} title="Änderung prüfen und freigeben"
      description="Nichts wird übertragen, bevor du freigibst."
      footer={
        <>
          <button type="button" disabled={laeuft} onClick={onClose}
                  className="rounded-md border px-3 py-1.5 text-sm"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            Später entscheiden
          </button>
          <button type="button" disabled={laeuft}
                  onClick={() => void entscheiden(() => api.rejectMutation(vorgang.mutation_id, 'lukas'))}
                  className="rounded-md border px-3 py-1.5 text-sm"
                  style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
            Ablehnen
          </button>
          <button type="button" disabled={laeuft}
                  onClick={() => void entscheiden(() => api.approveMutation(vorgang.mutation_id, 'lukas'))}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}>
            {laeuft && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Freigeben
          </button>
        </>
      }
    >
      {fehler && <ErrorState {...fehler} />}
      {vorgang.reused && (
        <p className="mb-3 text-sm" style={{ color: 'var(--color-text-muted)' }}>
          Dieser Vorgang war bereits vorbereitet. Es wurde kein zweiter angelegt.
        </p>
      )}
      <p className="text-sm">
        <strong>{COMMAND_LABELS[vorgang.command] ?? vorgang.command}</strong>
        {vorgang.target_label && <> · {vorgang.target_label}</>}
      </p>
      {vorgang.warnings.map((w) => (
        <p key={w} className="mt-2 text-sm" style={{ color: 'var(--color-danger, #b91c1c)' }}>{w}</p>
      ))}
      <div className="mt-3"><ChangeTable changes={vorgang.changes} /></div>
    </Modal>
  );
}

// ═══ Freigabe-Board ═════════════════════════════════════════════════════════
function ApprovalBoard({ onOpenMutation }: { onOpenMutation: (id: string) => void }) {
  const [eintraege, setEintraege] = useState<Approval[]>([]);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try { setEintraege(await api.listApprovals()); }
    catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, []);
  useEffect(() => { void laden(); }, [laden]);

  const handeln = async (fn: () => Promise<unknown>) => {
    try { await fn(); await laden(); } catch (e) { setFehler(fehlerbild(e)); }
  };

  if (laedt) return <LoadingState label="Freigaben werden geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (eintraege.length === 0) {
    // Auf der Freigabetafel ist „Keine Vorgänge" zweideutig — es könnte auch
    // heissen, dass Vorgänge existieren, aber nicht angezeigt werden.
    return <EmptyState title="Keine offenen Freigaben"
                       hint="Sobald du eine Änderung vorbereitest, erscheint sie hier." />;
  }

  return (
    <ul className="divide-y" style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}>
      {eintraege.map((a) => {
        const wartet = a.state === 'awaiting_approval';
        return (
          <li key={a.approval_id} className="py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium">
                  {COMMAND_LABELS[a.command] ?? a.command}
                  <button type="button" onClick={() => onOpenMutation(a.mutation_id)}
                          className="ml-2 text-sm underline"
                          style={{ color: 'var(--color-accent)' }}>
                    Vorgang öffnen
                  </button>
                </p>
                <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs"
                   style={{ color: 'var(--color-text-muted)' }}>
                  <span>Ausgelöst von {a.actor} ({a.initiation_context})</span>
                  <span>angefragt {a.requested_at}</span>
                  <span>gültig bis {a.expires_at}</span>
                  {a.is_expired
                    ? <Chip tone="warn">abgelaufen</Chip>
                    : <Chip>{a.state}</Chip>}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {wartet && !a.is_expired && (
                  <>
                    <button type="button"
                            onClick={() => void handeln(() => api.approveMutation(a.mutation_id, 'lukas'))}
                            className="rounded-md px-3 py-1 text-sm"
                            style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}>
                      Freigeben
                    </button>
                    <button type="button"
                            onClick={() => void handeln(() => api.rejectMutation(a.mutation_id, 'lukas'))}
                            className="rounded-md border px-3 py-1 text-sm"
                            style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
                      Ablehnen
                    </button>
                    <button type="button"
                            onClick={() => void handeln(() => api.cancelMutation(a.mutation_id, 'lukas'))}
                            className="rounded-md border px-3 py-1 text-sm"
                            style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
                      Abbrechen
                    </button>
                  </>
                )}
                {wartet && a.is_expired && (
                  <button type="button"
                          onClick={() => void handeln(() => api.expireMutation(a.mutation_id))}
                          className="rounded-md border px-3 py-1 text-sm"
                          style={{ borderColor: 'var(--color-warning, #b45309)' }}>
                    Als abgelaufen markieren
                  </button>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ═══ Mutationsstatus ════════════════════════════════════════════════════════
/**
 * Ob dieser Vorgang jetzt ausgeführt werden darf.
 *
 * Drei Bedingungen, alle notwendig: freigegeben, vom Provider unterstützt,
 * und noch nicht gesendet. Die Schaltfläche erscheint deshalb nur im Zustand
 * `approved` — jeder spätere Zustand bedeutet, dass bereits gesendet wurde.
 */
function kannAusfuehren(m: MutationDetail, caps: Capabilities | null): boolean {
  if (m.state !== 'approved') return false;
  if (m.command === 'create') return Boolean(caps?.create_supported);
  if (m.command === 'update') return Boolean(caps?.update_supported);
  return Boolean(caps?.delete_supported);
}

function MutationDetailView({ id, onBack }: { id: string; onBack: () => void }) {
  const [m, setM] = useState<MutationDetail | null>(null);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [gleichtAb, setGleichtAb] = useState(false);
  const [fuehrtAus, setFuehrtAus] = useState(false);
  const [loestAuf, setLoestAuf] = useState(false);
  const [fragtAbschluss, setFragtAbschluss] = useState(false);
  const [caps, setCaps] = useState<Capabilities | null>(null);

  useEffect(() => { api.getCapabilities().then(setCaps).catch(() => setCaps(null)); }, []);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try { setM(await api.getMutation(id)); }
    catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, [id]);
  useEffect(() => { void laden(); }, [laden]);

  if (laedt) return <LoadingState label="Vorgang wird geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (!m) return <EmptyState title="Vorgang nicht gefunden" />;

  return (
    <div>
      <button type="button" onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-sm"
              style={{ color: 'var(--color-text-muted)' }}>
        <ArrowLeft size={14} aria-hidden="true" /> Zurück
      </button>

      <h2 className="text-lg font-semibold">
        {COMMAND_LABELS[m.command] ?? m.command}
        {m.target_display_name && <> · {m.target_display_name}</>}
      </h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <StateChip state={m.state} />
        {m.last_error_code && <Chip tone="warn">{m.last_error_code}</Chip>}
        <Chip>Versuche: {m.attempt_count}</Chip>
      </div>

      {m.state === 'approved' && (
        <div className="mt-4 rounded-md border p-4"
             style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
          <p className="text-sm font-medium">Freigegeben — noch nicht ausgeführt.</p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Die Freigabe allein ändert bei Apple Kontakte nichts. Erst dieser
            Schritt überträgt den Vorgang, und er läuft genau einmal.
          </p>
          <button
            type="button" data-testid="ausfuehren"
            disabled={fuehrtAus || !kannAusfuehren(m, caps)}
            onClick={async () => {
              setFuehrtAus(true); setFehler(null);
              try { await api.executeMutation(m.mutation_id); await laden(); }
              catch (e) { setFehler(fehlerbild(e)); }
              // Bewusst kein `finally`: nach einem Lauf bleibt die Schaltflaeche
              // gesperrt, bis der neu geladene Zustand sie freigibt. Ein zweiter
              // Klick waehrend der Uebertragung kann so gar nicht entstehen.
              setFuehrtAus(false);
            }}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
            style={{
              backgroundColor: 'var(--color-accent)', color: '#fff',
              opacity: kannAusfuehren(m, caps) ? 1 : 0.5,
            }}
          >
            {fuehrtAus && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Jetzt ausführen
          </button>
          {!kannAusfuehren(m, caps) && (
            <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
              Diese Operation ist für Apple Kontakte noch nicht freigeschaltet.
            </p>
          )}
        </div>
      )}

      {m.state === 'provider_applied_pending_reconcile' && (
        <div className="mt-4 rounded-md border p-4" role="alert"
             style={{ borderColor: 'var(--color-warning, #b45309)' }}>
          <p className="text-sm font-medium">
            Bei Apple angelegt — lokale Übernahme steht noch aus.
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Der Kontakt existiert bereits bei Apple Kontakte; nur die lokale
            Kopie fehlt noch. Es wird deshalb **nichts** erneut übertragen —
            der Abgleich holt allein die lokale Übernahme nach.
          </p>
          <button
            type="button" disabled={gleichtAb} data-testid="nachfuehren"
            onClick={async () => {
              setGleichtAb(true); setFehler(null);
              try { await api.reconcileMutation(m.mutation_id); await laden(); }
              catch (e) { setFehler(fehlerbild(e)); }
              finally { setGleichtAb(false); }
            }}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
            style={{ borderColor: 'var(--color-warning, #b45309)' }}
          >
            {gleichtAb
              ? <Loader2 size={14} className="animate-spin" aria-hidden="true" />
              : <RefreshCw size={14} aria-hidden="true" />}
            Lokale Übernahme nachholen
          </button>
        </div>
      )}

      {m.state === 'outcome_unknown' && (
        <div className="mt-4 rounded-md border p-4" role="alert"
             style={{ borderColor: 'var(--color-warning, #b45309)' }}>
          <p className="text-sm font-medium">Der Ausgang ist unbekannt.</p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Die Änderung wurde möglicherweise schon ausgeführt — oder auch
            nicht. Ein zweiter Versuch könnte sie doppelt anwenden. Deshalb
            gibt es hier kein „erneut senden": Der einzige sichere Weg ist der
            Abgleich mit Apple Kontakte.
          </p>
          <button
            type="button" disabled={gleichtAb}
            onClick={async () => {
              setGleichtAb(true); setFehler(null);
              try { await api.reconcileMutation(m.mutation_id); await laden(); }
              catch (e) { setFehler(fehlerbild(e)); }
              finally { setGleichtAb(false); }
            }}
            className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
            style={{ borderColor: 'var(--color-warning, #b45309)' }}
          >
            {gleichtAb
              ? <Loader2 size={14} className="animate-spin" aria-hidden="true" />
              : <RefreshCw size={14} aria-hidden="true" />}
            Zustand abgleichen
          </button>
        </div>
      )}

      {(m.state === 'outcome_unknown'
        || m.state === 'manual_decision_required') && (
        <div className="mt-4 rounded-md border p-4"
             style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
          <p className="text-sm font-medium">
            Selbst in Apple Kontakte nachgesehen?
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Wenn du dort nachgeschaut hast und die Änderung <strong>nicht</strong>
            {' '}vorhanden ist, kannst du den Vorgang hier abschliessen. Es wird
            dabei <strong>nichts</strong> erneut übertragen — festgehalten wird
            nur, was du gesehen hast.
          </p>
          {!fragtAbschluss ? (
            <button
              type="button" data-testid="extern-geprueft"
              onClick={() => setFragtAbschluss(true)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm"
              style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}
            >
              Extern geprüft: Änderung nicht vorhanden
            </button>
          ) : (
            <div className="mt-3 rounded-md border p-3"
                 style={{ borderColor: 'var(--color-warning, #b45309)' }}>
              <p className="text-sm">
                Du bestätigst: Der Kontakt wurde in Apple Kontakte geprüft und
                die Änderung ist dort nicht vorhanden. Der Vorgang wird danach
                endgültig geschlossen und lässt sich nicht erneut ausführen.
              </p>
              <div className="mt-3 flex gap-2">
                <button type="button" onClick={() => setFragtAbschluss(false)}
                        className="rounded-md border px-3 py-1.5 text-sm"
                        style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
                  Abbrechen
                </button>
                <button
                  type="button" disabled={loestAuf} data-testid="abschluss-bestaetigen"
                  onClick={async () => {
                    setLoestAuf(true); setFehler(null);
                    try {
                      await api.resolveOutcomeNotObserved(m.mutation_id);
                      setFragtAbschluss(false);
                      await laden();
                    } catch (e) { setFehler(fehlerbild(e)); }
                    setLoestAuf(false);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                >
                  {loestAuf && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                  Ja, so abschliessen
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {m.state === 'manually_resolved_not_applied' && (
        <div className="mt-4 rounded-md border p-4"
             style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
          <p className="text-sm font-medium">
            Abgeschlossen: Änderung war beim Provider nicht vorhanden.
          </p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Das hast du nach eigener Prüfung festgehalten. Der technische
            Ausgang dieses Vorgangs war zum Zeitpunkt des Fehlers
            <strong> unbekannt</strong> — das bleibt in der Nachweiskette so
            stehen und wird durch den Abschluss nicht überschrieben. Ein
            erneuter Versuch wäre eine neue Änderung mit eigener Freigabe.
          </p>
        </div>
      )}

      {m.state === 'manual_decision_required' && (
        <div className="mt-4 rounded-md border p-4" role="alert"
             style={{ borderColor: 'var(--color-warning, #b45309)' }}>
          <p className="text-sm font-medium">Der Abgleich war nicht eindeutig.</p>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            Der beobachtete Zustand passt weder eindeutig zur erwarteten
            Änderung noch eindeutig dagegen. Automatisch wird hier nichts
            entschieden — bitte in Apple Kontakte nachsehen und danach
            entscheiden, ob ein neuer Vorgang nötig ist.
          </p>
          <dl className="mt-3 grid gap-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>
            <div className="flex gap-2">
              <dt>Erwartet:</dt>
              <dd>{m.changes.length} Feldänderung(en)</dd>
            </div>
            <div className="flex gap-2">
              <dt>Letzter technischer Code:</dt>
              <dd>{m.last_error_code ?? '—'}</dd>
            </div>
          </dl>
        </div>
      )}

      {m.state === 'failed_before_send' && (
        <p className="mt-4 rounded-md border p-4 text-sm"
           style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.3))' }}>
          Es wurde nachweislich nichts übertragen. Der Vorgang ist damit
          abgeschlossen; ein neuer Versuch ist eine neue Änderung mit eigener
          Freigabe.
        </p>
      )}

      <section className="mt-5">
        <h3 className="text-xs font-medium uppercase tracking-wide"
            style={{ color: 'var(--color-text-muted)' }}>Geplante Änderung</h3>
        <div className="mt-2"><ChangeTable changes={m.changes} /></div>
      </section>

      <dl className="mt-5 grid gap-1.5 text-sm sm:grid-cols-2">
        {[
          ['Ausgelöst von', `${m.actor} (${m.initiation_context})`],
          ['Angelegt', m.created_at],
          ['Freigegeben', m.approved_at ?? '—'],
          ['Abgeschlossen', m.completed_at ?? '—'],
          ['Erwartete Version', m.expected_revision ?? '—'],
          ['Freigabe', m.approval_state ?? '—'],
        ].map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt style={{ color: 'var(--color-text-muted)' }}>{k}:</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function MutationList({ onOpen }: { onOpen: (id: string) => void }) {
  const [items, setItems] = useState<Mutation[]>([]);
  const [laedt, setLaedt] = useState(true);
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);

  const laden = useCallback(async () => {
    setLaedt(true); setFehler(null);
    try { setItems(await api.listMutations()); }
    catch (e) { setFehler(fehlerbild(e)); } finally { setLaedt(false); }
  }, []);
  useEffect(() => { void laden(); }, [laden]);

  if (laedt) return <LoadingState label="Vorgänge werden geladen" />;
  if (fehler) return <ErrorState {...fehler} onRetry={() => void laden()} />;
  if (items.length === 0) return <EmptyState title="Noch keine Vorgänge" />;

  return (
    <ul className="divide-y" style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}>
      {items.map((m) => (
        <li key={m.mutation_id}>
          <button type="button" onClick={() => onOpen(m.mutation_id)}
                  className="flex w-full items-center gap-3 py-2.5 text-left">
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{COMMAND_LABELS[m.command] ?? m.command}</span>
                {m.target_display_name && <span className="truncate">{m.target_display_name}</span>}
                <StateChip state={m.state} />
              </span>
              <span className="mt-0.5 block text-xs" style={{ color: 'var(--color-text-muted)' }}>
                {m.created_at} · {m.actor}
              </span>
            </span>
            <ChevronRight size={16} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
          </button>
        </li>
      ))}
    </ul>
  );
}

// ═══ Seite ══════════════════════════════════════════════════════════════════

// ── App-Prozess-Save-SPIKE (isolierter Branch) ──────────────────────────────
//
// Nur sichtbar, wenn der App-Prozess mit OPENJARVIS_CONTACTS_APP_SAVE_SPIKE=1
// gestartet wurde. Fester Payload, genau eine Ausführung je App-Prozess,
// kein Retry — die Bestätigungsphrase muss wörtlich eingetippt werden.
function AppSaveSpikeSection() {
  const [status, setStatus] = useState<api.AppSaveSpikeStatus | null>(null);
  const [preview, setPreview] = useState<api.AppSaveSpikePreview | null>(null);
  const [eingabe, setEingabe] = useState('');
  const [ausgefuehrt, setAusgefuehrt] = useState(false);
  const [ergebnis, setErgebnis] = useState<api.AppSaveSpikeResult | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  useEffect(() => {
    api.appSaveSpikeStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!status?.enabled) return null;

  const vorbereiten = async () => {
    setFehler(null);
    try { setPreview(await api.appSaveSpikePrepare()); }
    catch (e) { setFehler(String(e)); }
  };

  const ausfuehren = async () => {
    if (!preview || ausgefuehrt) return;
    setAusgefuehrt(true);          // sofort und dauerhaft — kein zweiter Klick
    setFehler(null);
    try {
      setErgebnis(await api.appSaveSpikeExecute(
        eingabe, preview.nonce, preview.preview_digest));
    } catch (e) { setFehler(String(e)); }
  };

  return (
    <div data-testid="app-save-spike" className="mt-8 rounded-md border p-4"
         style={{ borderColor: 'var(--color-border, rgba(200,80,80,0.6))' }}>
      <h3 className="text-sm font-semibold">Contacts App-Process Save Spike</h3>
      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
        Nur für isolierte Entwicklungsprüfung. Es wird genau ein Testkontakt
        angelegt. Kein automatischer Wiederholungsversuch.
      </p>
      {!preview && (
        <button type="button" data-testid="spike-vorbereiten"
                onClick={vorbereiten}
                className="mt-2 rounded-md border px-3 py-1.5 text-sm">
          Spike vorbereiten
        </button>
      )}
      {preview && (
        <div className="mt-2 text-sm">
          <div>Vorname: <code>{preview.given_name}</code></div>
          <div>Ziel: {preview.container_type_label}</div>
          <div className="text-xs mt-1"
               style={{ color: 'var(--color-text-muted)' }}>
            {preview.notice}
          </div>
          <label className="block mt-2 text-xs">
            Zum Bestätigen wörtlich eintippen:{' '}
            <code>{preview.confirmation_phrase}</code>
            <input value={eingabe} data-testid="spike-phrase"
                   onChange={(e) => setEingabe(e.target.value)}
                   className="mt-1 w-full rounded-md border px-2 py-1" />
          </label>
          <button type="button" data-testid="spike-ausfuehren"
                  onClick={ausfuehren}
                  disabled={ausgefuehrt
                            || eingabe !== preview.confirmation_phrase}
                  className="mt-2 rounded-md border px-3 py-1.5 text-sm">
            Genau einmal ausführen
          </button>
        </div>
      )}
      {ergebnis && (
        <pre data-testid="spike-ergebnis" className="mt-2 text-xs overflow-auto">
          {JSON.stringify(ergebnis, null, 2)}
        </pre>
      )}
      {fehler && (
        <div data-testid="spike-fehler" className="mt-2 text-xs">{fehler}</div>
      )}
    </div>
  );
}

export default function ContactsPage() {
  const [tab, setTab] = useState<Tab>('contacts');
  const [kontaktId, setKontaktId] = useState<string | null>(null);
  const [mutationId, setMutationId] = useState<string | null>(null);
  const [anlegen, setAnlegen] = useState(false);
  const [vorschau, setVorschau] = useState<PreparedMutation | null>(null);
  const [nachladen, setNachladen] = useState(0);

  const tabs: { key: Tab; label: string }[] = [
    { key: 'contacts', label: 'Kontakte' },
    { key: 'approvals', label: 'Freigaben' },
    { key: 'mutations', label: 'Vorgänge' },
  ];

  return (
    <div className="mx-auto w-full max-w-5xl p-6">
      <h1 className="text-xl font-semibold">Kontakte</h1>
      <p className="mt-1 text-sm" style={{ color: 'var(--color-text-muted)' }}>
        Änderungen werden immer erst vorbereitet und von dir freigegeben.
        Nichts wird ungefragt übertragen.
      </p>

      <div className="mt-4 flex gap-1 border-b"
           style={{ borderColor: 'var(--color-border, rgba(127,127,127,0.2))' }}
           role="tablist" aria-label="Bereiche">
        {tabs.map((t) => (
          <button
            key={t.key} type="button" role="tab" id={`tab-${t.key}`}
            aria-selected={tab === t.key} aria-controls={`panel-${t.key}`}
            onClick={() => { setTab(t.key); setKontaktId(null); setMutationId(null); }}
            className="border-b-2 px-3 py-2 text-sm"
            style={{
              borderColor: tab === t.key ? 'var(--color-accent)' : 'transparent',
              color: tab === t.key ? 'var(--color-accent)' : 'var(--color-text-muted)',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="mt-5">
        {tab === 'contacts' && (
          kontaktId
            ? <ContactDetailView id={kontaktId} onBack={() => setKontaktId(null)}
                                 onPrepared={setVorschau} />
            : (
              <>
                <SyncPanel onSynced={() => setNachladen((n) => n + 1)} />
                <ContactList onOpen={setKontaktId} onCreate={() => setAnlegen(true)}
                             reloadKey={nachladen} />
              </>
            )
        )}
        {tab === 'approvals' && (
          mutationId
            ? <MutationDetailView id={mutationId} onBack={() => setMutationId(null)} />
            : <ApprovalBoard onOpenMutation={setMutationId} />
        )}
        {tab === 'mutations' && (
          mutationId
            ? <MutationDetailView id={mutationId} onBack={() => setMutationId(null)} />
            : <MutationList onOpen={setMutationId} />
        )}
      </div>

      <AppSaveSpikeSection />

      {anlegen && (
        <CreateDialog onClose={() => setAnlegen(false)}
                      onPrepared={(m) => { setAnlegen(false); setVorschau(m); }} />
      )}
      {vorschau && (
        <PreviewDialog vorgang={vorschau} onClose={() => setVorschau(null)}
                       onEntschieden={() => { setVorschau(null); setTab('approvals'); }} />
      )}
    </div>
  );
}

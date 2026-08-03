// Dialoge des Bearbeitungsflusses: Löschbestätigung, Vorschau/Freigabe und
// die Neuanlage (aus dem Bestand übernommen, auf die Datenquelle umgestellt).
//
// Alle Wege enden bei „vorbereitet" oder „freigegeben" — ausgeführt wird in
// diesem Auftrag nichts, und die Löschbestätigung warnt weiterhin vor der
// Unumkehrbarkeit einer späteren Ausführung: das lässt sich nicht rückgängig
// machen.

import { useEffect, useMemo, useState } from 'react';
import type { Capabilities, ContactDetail, PreparedMutation } from '../api';
import * as api from '../api';
import { ChangeTable, COMMAND_LABELS, Modal } from '../components';
import { aktionsKnopf } from '../detail/ContactDetailPane';
import type { ContactsDataSource } from '../data/source';
import type { Fehlerbild } from '../workspace/fehler';
import { fehlerbild } from '../workspace/fehler';

function FehlerZeile({ fehler }: { fehler: Fehlerbild | null }) {
  if (!fehler) return null;
  return (
    <p role="alert" style={{
      font: 'var(--pjc-font-body)', color: 'var(--color-danger)',
      margin: '0 0 10px',
    }}>
      {fehler.message}
      {fehler.technicalCode && (
        <span style={{
          display: 'block', font: 'var(--pjc-font-label)',
          color: 'var(--color-text-muted)', fontFamily: 'monospace',
        }}>
          Code: {fehler.technicalCode}
        </span>
      )}
    </p>
  );
}

export function DeleteBestaetigung({ kontakt, quelle, onClose, onPrepared }: {
  kontakt: ContactDetail;
  quelle: ContactsDataSource;
  onClose: () => void;
  onPrepared: (m: PreparedMutation) => void;
}) {
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [sendet, setSendet] = useState(false);

  return (
    <Modal
      open
      onClose={onClose}
      title="Kontakt löschen"
      description="Das Löschen wird vorbereitet und braucht danach deine Freigabe."
      footer={
        <>
          <button type="button" onClick={onClose} className="pjc-focusable"
                  style={aktionsKnopf(false)}>
            Abbrechen
          </button>
          <button
            type="button"
            disabled={sendet}
            data-testid="loeschen-vorbereiten"
            onClick={async () => {
              setSendet(true); setFehler(null);
              try {
                onPrepared(await quelle.prepareDelete(kontakt.id, {
                  expectedRevision: kontakt.revision,
                }));
              } catch (e) { setFehler(fehlerbild(e)); } finally { setSendet(false); }
            }}
            className="pjc-focusable pjc-primary"
            style={{
              ...aktionsKnopf(true),
              backgroundColor: 'var(--color-danger)',
              color: '#fff', border: 'none',
            }}
          >
            Löschen vorbereiten
          </button>
        </>
      }
    >
      <FehlerZeile fehler={fehler} />
      <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
        Zielkontakt: <strong>{kontakt.display_name}</strong>
      </p>
      <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-danger)', margin: '8px 0 0' }}>
        Nach Freigabe und Ausführung wäre der Datensatz bei Apple Kontakte
        gelöscht. Das lässt sich von hier aus nicht rückgängig machen.
      </p>
    </Modal>
  );
}

export function PreviewDialog({ vorgang, quelle, onClose, onEntschieden }: {
  vorgang: PreparedMutation;
  quelle: ContactsDataSource;
  onClose: () => void;
  onEntschieden: () => void;
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
      open
      onClose={onClose}
      title="Änderung prüfen und freigeben"
      description="Nichts wird übertragen, bevor du freigibst."
      footer={
        <>
          <button type="button" disabled={laeuft} onClick={onClose}
                  className="pjc-focusable" style={aktionsKnopf(false)}>
            Später entscheiden
          </button>
          <button type="button" disabled={laeuft}
                  onClick={() => void entscheiden(() => quelle.reject(vorgang.mutation_id, 'lukas'))}
                  className="pjc-focusable" style={aktionsKnopf(false)}>
            Ablehnen
          </button>
          <button type="button" disabled={laeuft} data-testid="vorschau-freigeben"
                  onClick={() => void entscheiden(() => quelle.approve(vorgang.mutation_id, 'lukas'))}
                  className="pjc-focusable pjc-primary"
                  style={{
                    ...aktionsKnopf(false),
                    backgroundColor: 'var(--pjc-selection-bg)',
                    color: 'var(--pjc-selection-fg)', border: 'none',
                  }}>
            Freigeben
          </button>
        </>
      }
    >
      <FehlerZeile fehler={fehler} />
      {vorgang.reused && (
        <p style={{ font: 'var(--pjc-font-body)', color: 'var(--color-text-muted)', margin: '0 0 10px' }}>
          Dieser Vorgang war bereits vorbereitet. Es wurde kein zweiter angelegt.
        </p>
      )}
      <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
        <strong>{COMMAND_LABELS[vorgang.command] ?? vorgang.command}</strong>
        {vorgang.target_label && <> · {vorgang.target_label}</>}
      </p>
      {vorgang.warnings.map((w) => (
        <p key={w} style={{ font: 'var(--pjc-font-body)', color: 'var(--color-warning)', margin: '8px 0 0' }}>
          {w}
        </p>
      ))}
      <div style={{ marginTop: '12px' }}><ChangeTable changes={vorgang.changes} /></div>
    </Modal>
  );
}

// ── Neuanlage (Feldvertrag v1, nur API-Betrieb, nur bei Capability) ────────
const ANLAGE_FELDER = [
  { key: 'given_name', label: 'Vorname' },
  { key: 'family_name', label: 'Nachname' },
  { key: 'nickname', label: 'Spitzname' },
  { key: 'organization_name', label: 'Organisation' },
  { key: 'department_name', label: 'Abteilung' },
  { key: 'job_title', label: 'Position' },
] as const;

const CONTAINER_ART: Record<string, string> = {
  local: 'Lokal · Auf meinem Mac',
  cardDAV: 'CardDAV / iCloud',
  exchange: 'Exchange',
  unassigned: 'Ohne Zuordnung',
  unknown: 'Art noch nicht bekannt',
};

export function CreateDialog({ caps, onClose, onPrepared }: {
  caps: Capabilities | null;
  onClose: () => void;
  onPrepared: (m: PreparedMutation) => void;
}) {
  const [werte, setWerte] = useState<Record<string, string>>({});
  const [orte, setOrte] = useState<api.ContainerOption[]>([]);
  const [ort, setOrt] = useState('');
  const [fehler, setFehler] = useState<Fehlerbild | null>(null);
  const [sendet, setSendet] = useState(false);

  useEffect(() => {
    api.listContainers()
      .then((o) => {
        setOrte(o);
        if (o.length === 1 && o[0].container_type !== 'unknown') {
          setOrt(o[0].container_ref);
        }
      })
      .catch(() => setOrte([]));
  }, []);

  const gefuellt = useMemo(
    () => Object.entries(werte).filter(([, v]) => v.trim() !== ''),
    [werte],
  );
  const vollstaendig = gefuellt.length > 0 && ort !== ''
    && Boolean(caps?.create_supported);

  return (
    <Modal
      open
      onClose={onClose}
      title="Kontakt anlegen"
      description="Der Kontakt wird vorbereitet und braucht danach deine Freigabe."
      footer={
        <>
          <button type="button" onClick={onClose} className="pjc-focusable"
                  style={aktionsKnopf(false)}>
            Abbrechen
          </button>
          <button
            type="button"
            disabled={sendet || !vollstaendig}
            data-testid="anlage-vorbereiten"
            onClick={async () => {
              setSendet(true); setFehler(null);
              try {
                onPrepared(await api.prepareCreate({
                  idempotencyKey: globalThis.crypto?.randomUUID?.() ?? `id-${Date.now()}`,
                  correlationId: globalThis.crypto?.randomUUID?.() ?? `id-${Date.now()}`,
                  containerRef: ort,
                  fields: Object.fromEntries(gefuellt.map(([k, v]) => [k, v.trim()])),
                }));
              } catch (e) { setFehler(fehlerbild(e)); } finally { setSendet(false); }
            }}
            className="pjc-focusable pjc-primary"
            style={{
              ...aktionsKnopf(false),
              backgroundColor: 'var(--pjc-selection-bg)',
              color: 'var(--pjc-selection-fg)', border: 'none',
              opacity: vollstaendig ? 1 : 0.5,
            }}
          >
            Anlage vorbereiten
          </button>
        </>
      }
    >
      <FehlerZeile fehler={fehler} />
      <div style={{ display: 'grid', gap: '10px', gridTemplateColumns: 'repeat(auto-fit, minmax(14rem, 1fr))' }}>
        <label style={{ font: 'var(--pjc-font-label)', gridColumn: '1 / -1' }}>
          <span style={{ display: 'block', color: 'var(--color-text-muted)' }}>Ablageort</span>
          <select
            value={ort}
            onChange={(e) => setOrt(e.target.value)}
            data-testid="anlage-ablageort"
            className="pjc-focusable"
            style={{
              font: 'var(--pjc-font-body)', width: '100%', marginTop: '2px',
              border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
              borderRadius: 'var(--pjc-radius-control)', padding: '3px 8px',
              background: 'transparent', color: 'var(--color-text)',
            }}
          >
            <option value="">Bitte wählen</option>
            {orte.map((o) => (
              <option key={o.container_ref} value={o.container_ref}>
                {CONTAINER_ART[o.container_type] ?? o.container_type}
                {' · '}{o.container_ref}
              </option>
            ))}
          </select>
        </label>
        {ANLAGE_FELDER.map((f) => (
          <label key={f.key} style={{ font: 'var(--pjc-font-label)' }}>
            <span style={{ display: 'block', color: 'var(--color-text-muted)' }}>{f.label}</span>
            <input
              value={werte[f.key] ?? ''}
              onChange={(e) => setWerte({ ...werte, [f.key]: e.target.value })}
              className="pjc-focusable"
              style={{
                font: 'var(--pjc-font-body)', width: '100%', marginTop: '2px',
                border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                borderRadius: 'var(--pjc-radius-control)', padding: '3px 8px',
                background: 'transparent', color: 'var(--color-text)',
              }}
            />
          </label>
        ))}
      </div>
    </Modal>
  );
}

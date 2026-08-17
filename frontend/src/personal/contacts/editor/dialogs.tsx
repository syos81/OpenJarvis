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
import {
  ChangeTable, COMMAND_LABELS, CONTAINER_ART, Modal, Zielangabe,
} from '../components';
import { aktionsKnopf } from '../detail/ContactDetailPane';
import type { ContactsDataSource } from '../data/source';
import type { Fehlerbild } from '../workspace/fehler';
import { fehlerbild } from '../workspace/fehler';
import { freigeben } from '../settings/freigabe';

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
                  onClick={() => void entscheiden(() => freigeben(vorgang, 'lukas'))}
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
      {/* Wohin — vor allem anderen. Die Zielangabe entsteht erst beim
          Vorbereiten; das Absenden des Formulars davor kann sie nicht
          zeigen und ist deshalb keine informierte Freigabe (§8 A). */}
      <Zielangabe command={vorgang.command}
                  targetLabel={vorgang.target_label}
                  containerRef={vorgang.container_ref}
                  containerType={vorgang.container_type}
                  containerName={vorgang.container_name}
                  containerContactCount={vorgang.container_contact_count} />
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

/// Etikettierte Listen der Neuanlage. Der Feldvertrag v1 kennt fünf; hier
/// stehen die beiden, die man beim Anlegen tatsächlich zur Hand hat. Die
/// übrigen (Anschriften, Web, Termine) folgen im Editor — sie einzeln in
/// diesen Dialog zu holen, machte ihn zu einem zweiten Editor.
const ANLAGE_LISTEN = [
  { key: 'emails', label: 'E-Mail', platzhalter: 'name@example.org',
    labels: ['home', 'work', 'other'] },
  { key: 'phones', label: 'Telefon', platzhalter: '+49 …',
    labels: ['mobile', 'home', 'work', 'main', 'other'] },
] as const;

const LABEL_TEXT: Record<string, string> = {
  home: 'Privat', work: 'Arbeit', other: 'Sonstige',
  mobile: 'Mobil', main: 'Hauptnummer',
};

type ListenEintrag = { label: string; value: string };

export function CreateDialog({ caps, onClose, onPrepared }: {
  caps: Capabilities | null;
  onClose: () => void;
  onPrepared: (m: PreparedMutation) => void;
}) {
  const [werte, setWerte] = useState<Record<string, string>>({});
  const [listen, setListen] = useState<Record<string, ListenEintrag[]>>({
    emails: [], phones: [],
  });
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
  // Leere Zeilen zählen nicht: Wer eine Zeile hinzufügt und nichts einträgt,
  // hat nichts eingetragen — und der Digest darf nicht davon abhängen.
  const gefuellteListen = useMemo(
    () => Object.fromEntries(
      Object.entries(listen)
        .map(([k, v]) => [k, v.filter((e) => e.value.trim() !== '')
          .map((e) => ({ label: e.label || null, value: e.value.trim() }))])
        .filter(([, v]) => (v as ListenEintrag[]).length > 0),
    ),
    [listen],
  );
  const vollstaendig = (gefuellt.length > 0
      || Object.keys(gefuellteListen).length > 0)
    && ort !== '' && Boolean(caps?.create_supported);

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
                  fields: {
                    ...Object.fromEntries(gefuellt.map(([k, v]) => [k, v.trim()])),
                    ...gefuellteListen,
                  },
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
        {ANLAGE_LISTEN.map((liste) => (
          <fieldset key={liste.key} style={{
            gridColumn: '1 / -1', border: 'none', padding: 0, margin: 0,
          }}>
            <legend style={{
              font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)',
              padding: 0,
            }}>
              {liste.label}
            </legend>
            {(listen[liste.key] ?? []).map((eintrag, i) => (
              <div key={i} style={{
                display: 'flex', gap: '6px', marginTop: '4px',
                alignItems: 'center',
              }}>
                <select
                  value={eintrag.label}
                  data-testid={`anlage-${liste.key}-label-${i}`}
                  onChange={(e) => setListen({
                    ...listen,
                    [liste.key]: (listen[liste.key] ?? []).map(
                      (x, j) => (j === i ? { ...x, label: e.target.value } : x)),
                  })}
                  className="pjc-focusable"
                  style={{
                    font: 'var(--pjc-font-body)', flex: '0 0 8rem',
                    border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                    borderRadius: 'var(--pjc-radius-control)', padding: '3px 6px',
                    background: 'transparent', color: 'var(--color-text)',
                  }}
                >
                  <option value="">ohne Etikett</option>
                  {liste.labels.map((l) => (
                    <option key={l} value={l}>{LABEL_TEXT[l] ?? l}</option>
                  ))}
                </select>
                <input
                  value={eintrag.value}
                  placeholder={liste.platzhalter}
                  data-testid={`anlage-${liste.key}-wert-${i}`}
                  onChange={(e) => setListen({
                    ...listen,
                    [liste.key]: (listen[liste.key] ?? []).map(
                      (x, j) => (j === i ? { ...x, value: e.target.value } : x)),
                  })}
                  className="pjc-focusable"
                  style={{
                    font: 'var(--pjc-font-body)', flex: 1,
                    border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                    borderRadius: 'var(--pjc-radius-control)', padding: '3px 8px',
                    background: 'transparent', color: 'var(--color-text)',
                  }}
                />
                <button
                  type="button" aria-label={`${liste.label} entfernen`}
                  onClick={() => setListen({
                    ...listen,
                    [liste.key]: (listen[liste.key] ?? [])
                      .filter((_, j) => j !== i),
                  })}
                  className="pjc-focusable"
                  style={{ ...aktionsKnopf(false), padding: '2px 8px' }}
                >
                  −
                </button>
              </div>
            ))}
            <button
              type="button"
              data-testid={`anlage-${liste.key}-hinzufuegen`}
              onClick={() => setListen({
                ...listen,
                [liste.key]: [...(listen[liste.key] ?? []),
                              { label: liste.labels[0], value: '' }],
              })}
              className="pjc-focusable"
              style={{ ...aktionsKnopf(false), marginTop: '4px' }}
            >
              + {liste.label}
            </button>
          </fieldset>
        ))}
      </div>
    </Modal>
  );
}

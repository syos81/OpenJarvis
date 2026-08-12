// Bearbeitungsmodus im Detailbereich: „Bearbeiten" → Felder ändern →
// „Fertig" bereitet die Änderung vor (nie ausführen), „Abbrechen" verwirft
// nach Rückfrage bei ungespeicherten Änderungen.
//
// Mutationsgrenze (bewusst, dokumentiert): Der Feldvertrag v1 überträgt die
// sechs Skalarfelder. Mehrwertfelder (E-Mail/Telefon/Adresse) sind hier
// editierbar, werden aber nur im Demo-Modus Teil des Fake-Vorgangs; im
// API-Betrieb kennzeichnet die Oberfläche sie als „erst mit erweitertem
// Feldvertrag übertragbar" und übergibt sie nicht. Es entsteht keine neue
// Mutationsarchitektur.

import { useEffect, useMemo, useState } from 'react';
import type { ContactDetail } from '../api';
import { Modal } from '../components';
import { aktionsKnopf } from '../detail/ContactDetailPane';
import type { Fehlerbild } from '../workspace/fehler';

export const SKALARFELDER = [
  { key: 'given_name', label: 'Vorname' },
  { key: 'family_name', label: 'Nachname' },
  { key: 'nickname', label: 'Spitzname' },
  { key: 'organization_name', label: 'Organisation' },
  { key: 'department_name', label: 'Abteilung' },
  { key: 'job_title', label: 'Position' },
] as const;

const MAIL_LABELS = ['home', 'work', 'other'] as const;
const TEL_LABELS = ['home', 'work', 'mobile', 'main', 'other'] as const;
const LABEL_TEXT: Record<string, string> = {
  home: 'Privat', work: 'Arbeit', mobile: 'Mobil', main: 'Haupt', other: 'Sonstige',
};

export interface MehrwertEintrag {
  schluessel: string;
  label: string;
  value: string;
}

interface Entwurf {
  skalar: Record<string, string>;
  emails: MehrwertEintrag[];
  phones: MehrwertEintrag[];
}

function entwurfAus(kontakt: ContactDetail): Entwurf {
  const skalar: Record<string, string> = {};
  for (const f of SKALARFELDER) {
    skalar[f.key] = (kontakt as unknown as Record<string, string | null>)[f.key] ?? '';
  }
  return {
    skalar,
    emails: kontakt.emails.map((w) => ({
      schluessel: w.id, label: w.label_normalized ?? 'other', value: w.value ?? '',
    })),
    phones: kontakt.phones.map((w) => ({
      schluessel: w.id, label: w.label_normalized ?? 'other', value: w.value ?? '',
    })),
  };
}

export function emailGueltig(wert: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(wert.trim());
}

let entwurfZaehler = 0;

function MehrwertEditor({ titel, eintraege, labels, onChange, gesperrt, fehlerText }: {
  titel: string;
  eintraege: MehrwertEintrag[];
  labels: readonly string[];
  onChange: (neu: MehrwertEintrag[]) => void;
  gesperrt: boolean;
  fehlerText: (wert: string) => string | null;
}) {
  return (
    <fieldset style={{
      border: 'none', margin: '16px 0 0', padding: 0,
      borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
      paddingTop: '12px',
    }}>
      <legend style={{
        font: 'var(--pjc-font-section)', textTransform: 'uppercase',
        color: 'var(--color-text-muted)', padding: 0,
      }}>
        {titel}
      </legend>
      {gesperrt && (
        <p style={{
          font: 'var(--pjc-font-label)', color: 'var(--color-text-muted)',
          margin: '4px 0 0',
        }}>
          Änderungen an {titel} sind erst mit einem erweiterten Feldvertrag
          übertragbar und werden hier noch nicht vorbereitet.
        </p>
      )}
      <div style={{ display: 'grid', gap: '6px', marginTop: '8px' }}>
        {eintraege.map((e, i) => {
          const fehler = e.value.trim() !== '' ? fehlerText(e.value) : null;
          const fehlerId = fehler ? `pjc-fehler-${e.schluessel}` : undefined;
          return (
            // Der Bezeichner steht links in derselben schmalen Spalte wie
            // die Namensfelder und traegt die Akzentfarbe — er ist ein
            // Bedienelement, kein Beschriftungstext. So loest die Referenz es.
            <div key={e.schluessel} style={{
              display: 'grid',
              gridTemplateColumns: 'var(--pjc-field-label-width) 1fr auto',
              gap: '10px',
              alignItems: 'start',
            }}>
              <select
                value={e.label}
                aria-label={`Art (${titel} ${i + 1})`}
                disabled={gesperrt}
                onChange={(ev) => {
                  const neu = [...eintraege];
                  neu[i] = { ...e, label: ev.target.value };
                  onChange(neu);
                }}
                className="pjc-focusable"
                style={{
                  ...eingabeStil(false),
                  border: 'none',
                  background: 'transparent',
                  color: 'var(--pjc-akzent-1)',
                  textAlign: 'right',
                  padding: '3px 0',
                }}
              >
                {labels.map((l) => <option key={l} value={l}>{LABEL_TEXT[l] ?? l}</option>)}
              </select>
              <div style={{ minWidth: 0 }}>
                <input
                  value={e.value}
                  aria-label={`${titel} ${i + 1}`}
                  aria-invalid={fehler ? true : undefined}
                  aria-describedby={fehlerId}
                  disabled={gesperrt}
                  onChange={(ev) => {
                    const neu = [...eintraege];
                    neu[i] = { ...e, value: ev.target.value };
                    onChange(neu);
                  }}
                  className="pjc-focusable"
                  style={{ ...eingabeStil(Boolean(fehler)), width: '100%' }}
                />
                {fehler && (
                  <p id={fehlerId} role="alert" style={{
                    font: 'var(--pjc-font-label)', color: 'var(--color-danger)',
                    margin: '2px 0 0',
                  }}>
                    {fehler}
                  </p>
                )}
              </div>
              {/* Entfernen als runde Marke in der Warnfarbe, wie in der
                  Referenz — kein Knopf mit Rahmen. */}
              <button
                type="button"
                aria-label={`${titel} ${i + 1} entfernen`}
                disabled={gesperrt}
                onClick={() => onChange(eintraege.filter((_, j) => j !== i))}
                className="pjc-focusable"
                style={{
                  width: '20px', height: '20px', marginTop: '3px',
                  borderRadius: '50%', border: 'none',
                  display: 'inline-flex', alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: gesperrt
                    ? 'var(--pjc-divider)' : 'var(--pjc-akzent-5)',
                  color: '#ffffff',
                  font: 'var(--pjc-font-label)',
                  lineHeight: 1,
                }}
              >
                −
              </button>
            </div>
          );
        })}
      </div>
      <button
        type="button"
        disabled={gesperrt}
        onClick={() => {
          entwurfZaehler += 1;
          onChange([...eintraege, {
            schluessel: `neu-${entwurfZaehler}`, label: labels[0], value: '',
          }]);
        }}
        className="pjc-focusable"
        style={{ ...aktionsKnopf(false), marginTop: '8px' }}
      >
        {titel} hinzufügen
      </button>
    </fieldset>
  );
}

export function ContactEditor({
  kontakt, demoModus, onFertig, onAbbrechen, onDreckig, sendet, fehler,
  listenSchreibbar = true,
}: {
  kontakt: ContactDetail;
  demoModus: boolean;
  /**
   * Ob etikettierte Listen übertragbar sind. Früher hing das am
   * Demo-Modus — eine Sperre aus der Zeit vor dem Update-Pfad, die im
   * API-Betrieb das Gegenteil dessen behauptete, was der Feldvertrag kann.
   * Jetzt entscheidet die Fähigkeit des Kanals.
   */
  listenSchreibbar?: boolean;
  /**
   * Übergibt die geänderten Felder des v1-Vertrags zur Vorbereitung —
   * Skalare **und** etikettierte Listen. Letztere waren im API-Betrieb
   * gesperrt, solange der Feldvertrag sie nicht schreiben konnte; seit dem
   * Update-Pfad kann er es, und die Sperre log den Nutzer an.
   */
  onFertig: (felder: Record<string, unknown>) => void;
  onAbbrechen: () => void;
  /**
   * Meldet nach aussen, ob ungesicherte Eingaben vorliegen. Der Workspace
   * laesst einen Kontaktwechsel nur zu, solange nichts geaendert wurde —
   * so wie die Referenz: ein unberuehrter Editor steht dem Weiterklicken
   * nicht im Weg, ein beschriebener schon.
   */
  onDreckig?: (dreckig: boolean) => void;
  sendet: boolean;
  fehler: Fehlerbild | null;
}) {
  const listenGesperrt = !demoModus && !listenSchreibbar;
  const start = useMemo(() => entwurfAus(kontakt), [kontakt]);
  const [entwurf, setEntwurf] = useState<Entwurf>(start);
  const [fragtAbbruch, setFragtAbbruch] = useState(false);

  const skalarDiff = useMemo(() => {
    const d: Record<string, string> = {};
    for (const [k, v] of Object.entries(entwurf.skalar)) {
      if (v !== start.skalar[k]) d[k] = v;
    }
    return d;
  }, [entwurf.skalar, start.skalar]);

  const listenGeaendert = (a: MehrwertEintrag[], b: MehrwertEintrag[]) =>
    JSON.stringify(a.map((e) => [e.label, e.value.trim()]))
    !== JSON.stringify(b.map((e) => [e.label, e.value.trim()]));
  const mehrwertGeaendert = listenGeaendert(entwurf.emails, start.emails)
    || listenGeaendert(entwurf.phones, start.phones);
  const dreckig = Object.keys(skalarDiff).length > 0 || mehrwertGeaendert;
  useEffect(() => { onDreckig?.(dreckig); }, [dreckig, onDreckig]);

  /**
   * Der vollständige Patch: geänderte Skalare plus **ganze** geänderte
   * Listen (v1 ersetzt je benannter Liste, ADR-0026 §8.2). Leere Zeilen
   * zählen nicht; eine geleerte Liste reist als `[]` und löscht damit
   * ausdrücklich — genau die Unterscheidung, die „weggelassen" von
   * „gelöscht" trennt.
   */
  const patch = useMemo(() => {
    const p: Record<string, unknown> = { ...skalarDiff };
    const liste = (werte: MehrwertEintrag[]) => werte
      .filter((e) => e.value.trim() !== '')
      .map((e) => ({ label: e.label || null, value: e.value.trim() }));
    if (listenGeaendert(entwurf.emails, start.emails)) p.emails = liste(entwurf.emails);
    if (listenGeaendert(entwurf.phones, start.phones)) p.phones = liste(entwurf.phones);
    return p;
  }, [skalarDiff, entwurf.emails, entwurf.phones, start.emails, start.phones]);

  const mailFehler = entwurf.emails.some(
    (e) => e.value.trim() !== '' && !emailGueltig(e.value),
  );
  const uebertragbar = Object.keys(patch).length > 0;
  const fertigMoeglich = dreckig && !mailFehler && uebertragbar && !sendet;

  const abbrechen = () => {
    if (dreckig) setFragtAbbruch(true);
    else onAbbrechen();
  };

  return (
    <div
      role="region"
      aria-label={`Kontakt ${kontakt.display_name} bearbeiten`}
      data-testid="contact-editor"
      onKeyDown={(e) => {
        if (e.key === 'Escape') { e.preventDefault(); abbrechen(); }
      }}
      style={{
        height: '100%',
        overflowY: 'auto',
        backgroundColor: 'var(--pjc-bg-detail)',
        padding: 'var(--pjc-detail-pad)',
      }}
    >
      {/* Inhaltsspalte wie in der Leseansicht: die Referenz zieht den Editor
          nicht über die volle Breite, sondern hält eine schmale Spalte. */}
      <div style={{ maxWidth: 'var(--pjc-card-width)', marginInline: 'auto' }}>

      <header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        gap: '12px',
      }}>
        <h2 style={{ font: 'var(--pjc-font-title)', margin: 0 }}>
          {kontakt.display_name}
        </h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button type="button" onClick={abbrechen} className="pjc-focusable"
                  data-testid="editor-abbrechen" style={aktionsKnopf(false)}>
            Abbrechen
          </button>
          <button
            type="button"
            onClick={() => onFertig(patch)}
            disabled={!fertigMoeglich}
            data-testid="editor-fertig"
            className="pjc-focusable pjc-primary"
            style={{
              ...aktionsKnopf(false),
              backgroundColor: 'var(--pjc-selection-bg)',
              color: 'var(--pjc-selection-fg)',
              border: 'none',
              opacity: fertigMoeglich ? 1 : 0.5,
            }}
          >
            Fertig
          </button>
        </div>
      </header>

      {fehler && (
        <p role="alert" style={{
          font: 'var(--pjc-font-body)', color: 'var(--color-danger)',
          margin: '10px 0 0',
        }}>
          {fehler.message}
        </p>
      )}

      {/* Namensfelder: Bezeichner rechtsbündig in einer schmalen Spalte, Wert
          daneben — der Aufbau der Referenz. Vorher lagen sie als breites
          Raster über die ganze Fläche. */}
      <div style={{ display: 'grid', gap: '6px', marginTop: '16px' }}>
        {SKALARFELDER.map((f) => (
          <label key={f.key} style={{
            display: 'grid',
            gridTemplateColumns: 'var(--pjc-field-label-width) 1fr',
            alignItems: 'center',
            gap: '10px',
            font: 'var(--pjc-font-body)',
          }}>
            <span style={{
              textAlign: 'right',
              font: 'var(--pjc-font-label)',
              color: 'var(--color-text-muted)',
            }}>
              {f.label}
            </span>
            <input
              value={entwurf.skalar[f.key] ?? ''}
              onChange={(e) => setEntwurf({
                ...entwurf,
                skalar: { ...entwurf.skalar, [f.key]: e.target.value },
              })}
              placeholder={f.label}
              className="pjc-focusable"
              style={{ ...eingabeStil(false), width: '100%' }}
            />
          </label>
        ))}
      </div>

      <MehrwertEditor
        titel="E-Mail"
        eintraege={entwurf.emails}
        labels={MAIL_LABELS}
        gesperrt={listenGesperrt}
        onChange={(emails) => setEntwurf({ ...entwurf, emails })}
        fehlerText={(w) => (emailGueltig(w) ? null : 'Keine gültige E-Mail-Adresse.')}
      />
      <MehrwertEditor
        titel="Telefon"
        eintraege={entwurf.phones}
        labels={TEL_LABELS}
        gesperrt={listenGesperrt}
        onChange={(phones) => setEntwurf({ ...entwurf, phones })}
        fehlerText={() => null}
      />

      {fragtAbbruch && (
        <Modal
          open
          onClose={() => setFragtAbbruch(false)}
          title="Änderungen verwerfen?"
          description="Der Kontakt wurde geändert, aber noch nichts vorbereitet."
          footer={
            <>
              <button type="button" onClick={() => setFragtAbbruch(false)}
                      className="pjc-focusable" style={aktionsKnopf(false)}>
                Weiter bearbeiten
              </button>
              <button type="button" data-testid="abbruch-verwerfen"
                      onClick={() => { setFragtAbbruch(false); onAbbrechen(); }}
                      className="pjc-focusable" style={aktionsKnopf(true)}>
                Verwerfen
              </button>
            </>
          }
        >
          <p style={{ font: 'var(--pjc-font-body)', margin: 0 }}>
            Beim Verwerfen gehen die ungespeicherten Änderungen verloren.
          </p>
        </Modal>
      )}
      </div>
    </div>
  );
}

function eingabeStil(fehlerhaft: boolean): React.CSSProperties {
  return {
    font: 'var(--pjc-font-body)',
    border: `var(--pjc-divider-width) solid ${fehlerhaft ? 'var(--color-danger)' : 'var(--pjc-divider)'}`,
    borderRadius: 'var(--pjc-radius-control)',
    padding: '3px 8px',
    minHeight: 'var(--pjc-hit-target)',
    background: 'transparent',
    color: 'var(--color-text)',
  };
}

// Rechte Spalte: die ruhige Apple-Detailansicht eines Kontakts.
//
// Keine technischen Identifier, keine Audit-Hashes, keine Providerdetails —
// solche Angaben gehören in die Statusfläche, nicht hierher. Fehlende Werte
// erzeugen keine leeren Karten: eine Feldgruppe ohne Inhalt erscheint nicht.

import { useState } from 'react';
import type { Capabilities, ContactDetail, LabeledValue } from '../api';
import { Chip, availabilityOf } from '../components';
import { avatarFarbe, initialen } from '../list/ContactsListPane';
import type { Fehlerbild } from '../workspace/fehler';

const LABEL_TEXT: Record<string, string> = {
  home: 'Privat', work: 'Arbeit', mobile: 'Mobil', main: 'Haupt',
  other: 'Sonstige', homepage: 'Homepage',
};

export function labelText(roh: string | null): string {
  if (!roh) return '';
  return LABEL_TEXT[roh] ?? roh;
}

/** Eine Feldzeile: Label ueber dem Wert, wie in der Referenz auf dem M2. */
function FieldRow({ label, kinder }: { label: string; kinder: React.ReactNode }) {
  return (
    <div>
      <dt style={{
        font: 'var(--pjc-font-label)',
        color: 'var(--color-text-muted)',
      }}>
        {label}
      </dt>
      <dd style={{
        margin: 0, minWidth: 0,
        font: 'var(--pjc-font-body)',
        overflowWrap: 'anywhere',
      }}>
        {kinder}
      </dd>
    </div>
  );
}

/** Karte statt Trennlinie: die Referenz gruppiert Felder in gerundete Flaechen. */
export function kartenFlaeche(): React.CSSProperties {
  return {
    background: 'var(--pjc-card-bg)',
    borderRadius: 'var(--pjc-card-radius)',
    padding: 'var(--pjc-card-pad)',
    marginTop: 'var(--pjc-card-gap)',
  };
}

function FieldSection({ titel, werte }: { titel: string; werte: LabeledValue[] }) {
  if (werte.length === 0) return null;
  return (
    <section aria-label={titel} style={kartenFlaeche()}>
      <dl style={{ margin: 0, display: 'grid', gap: 'var(--pjc-card-gap)' }}>
        {werte.map((w) => (
          <FieldRow
            key={w.id}
            label={labelText(w.label_normalized) || titel}
            kinder={w.value ?? '—'}
          />
        ))}
      </dl>
    </section>
  );
}

function AddressBlock({ adressen }: { adressen: LabeledValue[] }) {
  if (adressen.length === 0) return null;
  return (
    <section aria-label="Adressen" style={kartenFlaeche()}>
      <dl style={{ margin: 0, display: 'grid', gap: 'var(--pjc-card-gap)' }}>
        {adressen.map((a) => {
          const zeilen = [
            String(a.extra.street ?? ''),
            [a.extra.postal_code, a.extra.city].filter(Boolean).join(' '),
            String(a.extra.country ?? ''),
          ].filter((z) => z.trim() !== '');
          return (
            <FieldRow
              key={a.id}
              label={labelText(a.label_normalized) || 'Adresse'}
              kinder={
                <span style={{ whiteSpace: 'pre-line' }}>
                  {zeilen.join('\n') || '—'}
                </span>
              }
            />
          );
        })}
      </dl>
    </section>
  );
}

export function ContactDetailPane({
  kontakt, caps, nichtImFilter, onBearbeiten, onLoeschen, onRolleHinzu,
  onRolleWeg, fehler,
}: {
  kontakt: ContactDetail;
  caps: Capabilities | null;
  /** Der Kontakt ist ausgewählt, fällt aber aus dem aktiven Filter. */
  nichtImFilter: boolean;
  onBearbeiten: () => void;
  onLoeschen: () => void;
  onRolleHinzu: (rolle: string) => void;
  onRolleWeg: (rolle: string) => void;
  fehler: Fehlerbild | null;
}) {
  const [neueRolle, setNeueRolle] = useState('');

  const aenderbar = !kontakt.is_me_card && kontakt.writable
    && Boolean(caps?.update_supported);
  const loeschbar = !kontakt.is_me_card && kontakt.writable
    && Boolean(caps?.delete_supported);
  const notizZustand = availabilityOf(kontakt.field_availability, 'note');
  const untertitel = [kontakt.job_title, kontakt.department_name,
    kontakt.organization_name].filter(Boolean).join(' · ');

  const geburtstag = kontakt.birthday_day && kontakt.birthday_month
    ? `${String(kontakt.birthday_day).padStart(2, '0')}.`
      + `${String(kontakt.birthday_month).padStart(2, '0')}.`
      + `${kontakt.birthday_year ?? ''}`.replace(/\.$/, '')
    : null;

  return (
    <article
      role="region"
      aria-label={`Kontakt ${kontakt.display_name}`}
      data-testid="contact-detail"
      style={{
        height: '100%',
        overflowY: 'auto',
        backgroundColor: 'var(--pjc-bg-detail)',
        padding: 'var(--pjc-detail-pad)',
      }}
    >
      {/* Inhaltsspalte. M2 gemessen: die Karten sind 559 pt breit und mittig
          im Panel, nicht ueber dessen volle Breite gezogen. */}
      <div style={{
        maxWidth: 'var(--pjc-card-width)',
        marginInline: 'auto',
      }}>
      {nichtImFilter && (
        <p role="status" style={{
          font: 'var(--pjc-font-label)',
          color: 'var(--color-text-muted)',
          margin: '0 0 12px',
        }}>
          Dieser Kontakt liegt ausserhalb des aktuellen Filters. Die Auswahl
          bleibt erhalten.
        </p>
      )}

      {/* Hero — zentriert, Avatar oben, Name darunter. So zeigt es die
          Referenz auf dem M2; vorher stand der Name neben dem Avatar. */}
      <header style={{
        display: 'flex', flexDirection: 'column', gap: '12px',
        alignItems: 'center', textAlign: 'center',
      }}>
        {/* Die Breite ist gemessen, die Deckelung auf 30 % haelt den Kreis
            auch in einem schmalen Panel im Rahmen. Die Hoehe folgt ueber das
            Seitenverhaeltnis — eine prozentuale Hoehe haette keinen Bezug und
            wuerde auf null zusammenfallen. Die Initialen skalieren mit der
            Box (Container-Einheit) statt mit einer festen Zahl. */}
        <span aria-hidden="true" style={{
          width: 'min(var(--pjc-avatar-hero), 30%)',
          aspectRatio: '1',
          borderRadius: '50%',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: avatarFarbe(kontakt.display_name),
          backgroundColor: `color-mix(in srgb, ${avatarFarbe(kontakt.display_name)} `
            + `var(--pjc-akzent-fond), transparent)`,
          flex: '0 0 auto',
          containerType: 'inline-size',
        }}>
          <span style={{ font: 'var(--pjc-font-hero)', fontSize: '38cqw' }}>
            {initialen(kontakt.display_name)}
          </span>
        </span>
        <div style={{ minWidth: 0 }}>
          <h2 style={{ font: 'var(--pjc-font-hero)', margin: 0, overflowWrap: 'anywhere' }}>
            {kontakt.display_name}
          </h2>
          {untertitel && (
            <p style={{
              font: 'var(--pjc-font-body)',
              color: 'var(--color-text-muted)',
              margin: '2px 0 0',
              overflowWrap: 'anywhere',
            }}>
              {untertitel}
            </p>
          )}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px',
            justifyContent: 'center',
          }}>
            {kontakt.is_me_card && (
              <Chip tone="info" title="Die eigene Karte ist in dieser Version schreibgeschützt.">
                Meine Karte
              </Chip>
            )}
            {kontakt.unified_read_only && (
              <Chip title="Verknüpfte Karten werden nur gelesen.">verknüpfte Ansicht</Chip>
            )}
            {kontakt.conflict_state && <Chip tone="warn">Konflikt</Chip>}
            {kontakt.account_refs.length > 1 && (
              <Chip title="Dieser Kontakt stammt aus mehreren Konten.">
                {kontakt.account_refs.length} Quellen
              </Chip>
            )}
          </div>
        </div>
      </header>

      {/* Keine Aktionsknoepfe in der Karte. Die Referenz auf dem M2 haelt
          „Bearbeiten" oben in der Toolbar und alles Weitere im Rechtsklick;
          die Karte selbst zeigt nur den Kontakt. `onBearbeiten` und
          `onLoeschen` bleiben Teil des Vertrags dieser Komponente — der
          Workspace loest beides jetzt von dort aus. */}

      {fehler && (
        <p role="alert" style={{
          font: 'var(--pjc-font-body)', color: 'var(--color-danger)',
          margin: '12px 0 0',
        }}>
          {fehler.message}
        </p>
      )}

      <div style={{ marginTop: 'var(--pjc-detail-gap)' }}>
        <FieldSection titel="Telefon" werte={kontakt.phones} />
        <FieldSection titel="E-Mail" werte={kontakt.emails} />
        <FieldSection titel="Web" werte={kontakt.urls} />
        <AddressBlock adressen={kontakt.postal_addresses} />

        {(geburtstag || kontakt.nickname) && (
          <section aria-label="Weitere Angaben" style={{
            borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
            paddingTop: 'var(--pjc-detail-gap)',
            marginTop: 'var(--pjc-detail-gap)',
          }}>
            <dl style={{ margin: 0, display: 'grid', gap: '6px' }}>
              {geburtstag && <FieldRow label="Geburtstag" kinder={geburtstag} />}
              {kontakt.nickname && <FieldRow label="Spitzname" kinder={kontakt.nickname} />}
            </dl>
          </section>
        )}

        {kontakt.relations.length > 0 && (
          <section aria-label="Beziehungen" style={{
            borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
            paddingTop: 'var(--pjc-detail-gap)',
            marginTop: 'var(--pjc-detail-gap)',
          }}>
            <dl style={{ margin: 0, display: 'grid', gap: '6px' }}>
              {kontakt.relations.map((r) => (
                <FieldRow
                  key={r.id}
                  label={String(r.extra.relation_type ?? 'Beziehung')}
                  kinder={String(r.extra.target_name_raw ?? '—')}
                />
              ))}
            </dl>
          </section>
        )}

        {/* Notiz: „nicht lesbar" darf nie wie „leer" aussehen — aber leise:
            eine gedämpfte Zeile mit Tooltip statt Warnkasten auf jeder Karte. */}
        {notizZustand === 'unavailable_by_capability' && (
          <section aria-label="Notiz" style={{
            borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
            paddingTop: 'var(--pjc-detail-gap)',
            marginTop: 'var(--pjc-detail-gap)',
          }}>
            <dl style={{ margin: 0 }}>
              <FieldRow label="Notiz" kinder={
                <span
                  style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}
                  title="Ob eine Notiz existiert, ist unbekannt: Notizen benötigen eine besondere Apple-Berechtigung, die dieses Programm nicht hat. Das Feld gilt nicht als leer und wird nie überschrieben."
                >
                  nicht lesbar
                </span>
              } />
            </dl>
          </section>
        )}

        {/* Lokale Kategorien */}
        <section aria-label="Kategorien" style={{
          borderTop: 'var(--pjc-divider-width) solid var(--pjc-divider)',
          paddingTop: 'var(--pjc-detail-gap)',
          marginTop: 'var(--pjc-detail-gap)',
        }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
            <span style={{
              font: 'var(--pjc-font-label)',
              color: 'var(--color-text-muted)',
              flex: `0 0 var(--pjc-field-label-width)`,
              textAlign: 'right',
              marginRight: '12px',
            }}>
              Kategorien
            </span>
            {kontakt.roles.map((r) => (
              <span key={r} style={{
                display: 'inline-flex', alignItems: 'center', gap: '4px',
                font: 'var(--pjc-font-label)',
                border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                borderRadius: '999px',
                padding: '1px 8px',
              }}>
                {r}
                <button
                  type="button"
                  aria-label={`Kategorie ${r} entfernen`}
                  onClick={() => onRolleWeg(r)}
                  className="pjc-focusable"
                  style={{
                    border: 'none', background: 'none',
                    font: 'inherit', color: 'var(--color-text-muted)',
                    minWidth: 'var(--pjc-hit-target)', minHeight: 'var(--pjc-hit-target)',
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    margin: '-4px -6px -4px -2px',
                  }}
                >
                  ×
                </button>
              </span>
            ))}
            <form
              style={{ display: 'inline-flex', gap: '4px' }}
              onSubmit={(e) => {
                e.preventDefault();
                if (!neueRolle.trim()) return;
                onRolleHinzu(neueRolle.trim());
                setNeueRolle('');
              }}
            >
              <input
                value={neueRolle}
                onChange={(e) => setNeueRolle(e.target.value)}
                aria-label="Neue Kategorie"
                placeholder="Kategorie…"
                className="pjc-focusable"
                style={{
                  font: 'var(--pjc-font-label)',
                  border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
                  borderRadius: 'var(--pjc-radius-control)',
                  padding: '2px 8px',
                  width: '9rem',
                  background: 'transparent',
                  color: 'var(--color-text)',
                }}
              />
              <button type="submit" className="pjc-focusable" style={aktionsKnopf(false)}>
                Hinzufügen
              </button>
            </form>
          </div>
          <p style={{
            font: 'var(--pjc-font-label)',
            color: 'var(--color-text-muted)',
            margin: '6px 0 0',
            paddingLeft: 'calc(var(--pjc-field-label-width) + 12px)',
          }}>
            Kategorien bleiben auf diesem Mac.
          </p>
        </section>
      </div>
      </div>
    </article>
  );
}

export function aktionsKnopf(gefaehrlich: boolean): React.CSSProperties {
  return {
    font: 'var(--pjc-font-body)',
    border: 'var(--pjc-divider-width) solid var(--pjc-divider)',
    borderRadius: 'var(--pjc-radius-control)',
    padding: '3px 12px',
    minHeight: 'var(--pjc-hit-target)',
    background: 'transparent',
    color: gefaehrlich ? 'var(--color-danger)' : 'var(--color-text)',
    cursor: 'pointer',
  };
}

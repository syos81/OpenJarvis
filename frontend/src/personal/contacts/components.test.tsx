// Darstellung der Kontakte-Oberfläche.
//
// Gerendert wird mit `react-dom/server` statt mit jsdom: das Repo testet
// bewusst ohne DOM-Abhängigkeit (src/lib/api.auth.test.ts), und eine neue
// Testabhängigkeit wäre eine Lockfile-Änderung. Damit sind Auszeichnung,
// Beschriftung und Zugänglichkeitsattribute prüfbar; ereignisgesteuertes
// Verhalten (Tastaturfalle, Klicks) ist es nicht — siehe die statischen
// Prüfungen am Ende dieser Datei und den Gate-D-Bericht.

import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  ChangeTable,
  Chip,
  COMMAND_LABELS,
  EmptyState,
  ErrorState,
  FieldStateBadge,
  LoadingState,
  MUTATION_LABELS,
  Modal,
  StateChip,
  availabilityOf,
} from './components';

const html = (node: React.ReactElement) => renderToStaticMarkup(node);
const HIER = dirname(fileURLToPath(import.meta.url));
const quelle = (datei: string) => readFileSync(join(HIER, datei), 'utf8');

// ── Zustandsflächen ────────────────────────────────────────────────────────
describe('Lade-, Leer- und Fehlerzustand', () => {
  it('meldet das Laden an Hilfstechnik', () => {
    const m = html(<LoadingState label="Kontakte werden geladen" />);
    expect(m).toContain('role="status"');
    expect(m).toContain('aria-live="polite"');
    expect(m).toContain('Kontakte werden geladen');
  });

  it('erklaert die Leere statt sie unkommentiert zu zeigen', () => {
    const m = html(<EmptyState title="Keine Kontakte" hint="Erst synchronisieren." />);
    expect(m).toContain('Keine Kontakte');
    expect(m).toContain('Erst synchronisieren.');
  });

  it('kennzeichnet Fehler als Alarm und zeigt die Meldung', () => {
    const m = html(<ErrorState message="Kollision beim Speichern" />);
    expect(m).toContain('role="alert"');
    expect(m).toContain('Kollision beim Speichern');
  });
});

// ── Feldverfügbarkeit: der teuerste Verwechslungsfehler ────────────────────
describe('Feldverfuegbarkeit', () => {
  it('unterscheidet „nicht lesbar" von „leer"', () => {
    const gesperrt = html(<FieldStateBadge state="unavailable_by_capability" />);
    const leer = html(<FieldStateBadge state="absent" />);
    expect(gesperrt).toContain('nicht lesbar');
    expect(leer).toContain('leer');
    expect(gesperrt).not.toContain('>leer<');
  });

  it('sagt beim gesperrten Feld ausdruecklich, dass es nicht als leer gilt', () => {
    const m = html(<FieldStateBadge state="unavailable_by_capability" />);
    expect(m).toContain('nicht als leer');
  });

  it('zeigt bei vorhandenem Feld gar keinen Hinweis', () => {
    expect(html(<FieldStateBadge state="present" />)).toBe('');
  });

  it('findet den Zustand eines benannten Feldes', () => {
    const liste = [{ field_name: 'note', state: 'unavailable_by_capability' as const }];
    expect(availabilityOf(liste, 'note')).toBe('unavailable_by_capability');
    expect(availabilityOf(liste, 'nickname')).toBeNull();
  });
});

// ── Mutationszustände ──────────────────────────────────────────────────────
describe('Zustandsbeschriftung', () => {
  it('beschriftet jeden Zustand der Gate-C-Maschine auf Deutsch', () => {
    for (const zustand of [
      'prepared', 'awaiting_approval', 'approved', 'rejected', 'expired',
      'cancelled', 'executing', 'succeeded', 'failed_before_send',
      'outcome_unknown', 'reconcile_required', 'manual_decision_required',
      'failed',
    ]) {
      expect(MUTATION_LABELS[zustand]).toBeTruthy();
      expect(html(<StateChip state={zustand} />)).toContain(MUTATION_LABELS[zustand]);
    }
  });

  it('nennt den unbekannten Ausgang beim Namen statt ihn als Fehler zu tarnen', () => {
    expect(MUTATION_LABELS.outcome_unknown).toBe('Ausgang unbekannt');
    expect(MUTATION_LABELS.failed_before_send).toContain('nichts gesendet');
  });

  it('beschriftet die drei Befehle', () => {
    expect(COMMAND_LABELS).toEqual({
      create: 'Anlegen', update: 'Ändern', delete: 'Löschen',
    });
  });

  it('faerbt unklare Ausgaenge warnend, nicht neutral', () => {
    const warn = html(<StateChip state="outcome_unknown" />);
    const neutral = html(<StateChip state="prepared" />);
    expect(warn).not.toBe(neutral);
    expect(warn).toContain('warning');
  });
});

// ── Vorher/Nachher ─────────────────────────────────────────────────────────
describe('Änderungstabelle', () => {
  const changes = [
    { field_name: 'nickname', previous: null, planned: 'Kurz' },
    { field_name: 'job_title', previous: 'Alt', planned: 'Neu' },
  ];

  it('zeigt beide Seiten jeder Aenderung', () => {
    const m = html(<ChangeTable changes={changes} />);
    expect(m).toContain('nickname');
    expect(m).toContain('Kurz');
    expect(m).toContain('Alt');
    expect(m).toContain('Neu');
  });

  it('ist als Tabelle beschriftet und ausgezeichnet', () => {
    const m = html(<ChangeTable changes={changes} />);
    expect(m).toContain('<caption');
    expect(m).toContain('scope="col"');
    expect(m).toContain('scope="row"');
  });

  it('macht das Fehlen eines bisherigen Werts sichtbar', () => {
    expect(html(<ChangeTable changes={changes} />)).toContain('—');
  });

  it('behauptet bei leerer Liste keine Aenderung', () => {
    expect(html(<ChangeTable changes={[]} />)).toContain('Keine Feldänderung');
  });
});

// ── Dialog ─────────────────────────────────────────────────────────────────
describe('Dialog', () => {
  it('rendert geschlossen nichts', () => {
    expect(html(
      <Modal open={false} onClose={() => {}} title="X">Inhalt</Modal>,
    )).toBe('');
  });

  it('ist als modaler Dialog ausgezeichnet und beschriftet', () => {
    const m = html(
      <Modal open onClose={() => {}} title="Änderung prüfen" description="Vorher/Nachher">
        Inhalt
      </Modal>,
    );
    expect(m).toContain('role="dialog"');
    expect(m).toContain('aria-modal="true"');
    expect(m).toContain('aria-labelledby="pj-modal-title"');
    expect(m).toContain('aria-describedby="pj-modal-desc"');
    expect(m).toContain('Änderung prüfen');
  });
});

describe('Chip', () => {
  it('traegt den erklaerenden Titel weiter', () => {
    expect(html(<Chip title="Erklaerung">Text</Chip>)).toContain('title="Erklaerung"');
  });
});

// ── Statische Zusicherungen über den Seitencode ────────────────────────────
//
// Diese Prüfungen ersetzen nicht, was nur mit einem DOM prüfbar wäre. Sie
// sichern die Eigenschaften, die überhaupt nicht verletzt werden dürfen —
// und die in einem Renderlauf gar nicht sichtbar würden.
describe('Seitencode', () => {
  const seite = quelle('ContactsPage.tsx');
  const klient = quelle('api.ts');

  it('ruft keinen Provider, Sidecar oder Store direkt auf', () => {
    for (const verboten of [
      'fetch(', 'invoke(', 'tauri', 'sidecar', 'jarvis-contacts',
      'CNContact', 'requestAuthorization', 'AddressBook',
    ]) {
      expect(seite.toLowerCase()).not.toContain(verboten.toLowerCase());
    }
  });

  it('haelt Synchronisationstoken vollstaendig aus der Oberflaeche heraus', () => {
    for (const verboten of ['cursor_token', 'history_token', 'key_set_version',
                            'currentHistoryToken']) {
      expect(seite).not.toContain(verboten);
      expect(klient).not.toContain(verboten);
    }
  });

  it('bietet nirgends ein erneutes Senden an', () => {
    for (const verboten of ['Erneut senden', 'Nochmal senden', 'retrySend',
                            'resend']) {
      expect(seite).not.toContain(verboten);
    }
  });

  it('nennt beim unbekannten Ausgang den Abgleich als einzigen Weg', () => {
    expect(seite).toContain('Zustand abgleichen');
  });

  it('warnt beim Loeschen vor der Unumkehrbarkeit', () => {
    expect(seite.toLowerCase()).toContain('nicht rückgängig');
  });

  it('bindet die Seite genau einmal in Route und Navigation ein', () => {
    const app = readFileSync(join(HIER, '../../App.tsx'), 'utf8');
    const sidebar = readFileSync(
      join(HIER, '../../components/Sidebar/Sidebar.tsx'), 'utf8');
    expect(app.match(/path="contacts"/g)).toHaveLength(1);
    expect(sidebar.match(/path: '\/contacts'/g)).toHaveLength(1);
  });
});

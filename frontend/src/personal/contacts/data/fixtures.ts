// Synthetische Kontakte für Demo-Modus, Tests und Performanceprüfungen.
//
// AUSSCHLIESSLICH erfundene Daten: Namen sind sichtbar synthetisch,
// E-Mail-Domains enden auf `.invalid` (RFC 2606, nie zustellbar), Nummern
// liegen im nicht vergebenen Bereich `+49 000 …`. Die Erzeugung ist rein
// indexbasiert und damit deterministisch — gleicher Aufruf, gleiche Daten,
// ohne Zufall und ohne Uhr.

import type {
  ContactDetail, ContactSummary, LabeledValue, RoleCount,
} from '../api';
import { sortiereKontakte } from './sortierung';

const VORNAMEN = [
  'Alva', 'Bela', 'Céline', 'Dörte', 'Émile', 'Fiete', 'Gül', 'Henrik',
  'Ingrid', 'Jörn', 'Käthe', 'Lino', 'Mila', 'Nuray', 'Ólafur', 'Pia',
  'Quirin', 'Ruth', 'Sören', 'Tessa', 'Ümit', 'Vera', 'Wanja', 'Xenia',
  'Yusuf', 'Zoë',
] as const;

const NACHNAMEN = [
  'Attrappe', 'Beispiel', 'Chiffre', 'Demofrau', 'Erfunden', 'Fiktiv',
  'Gestellt', 'Hypothes', 'Imaginär', 'Jotdemo', 'Kunstfigur', 'Lehrbeispiel',
  'Muster', 'Nurtest', 'Ohnegleichen', 'Probe', 'Quasiecht', 'Rollenspiel',
  'Synthetik', 'Testmann', 'Übungsfall', 'Vorlage', 'Werkstück', 'Xemplar',
  'Ypsilontest', 'Zierbeispiel',
] as const;

const ORGANISATIONEN = [
  null, 'Beispiel GmbH', 'Muster AG', 'Synthetik e. V.', null,
  'Demo-Labor Süd', 'Übungswerk KG', null, 'Attrappen-Kontor', null,
] as const;

const ROLLEN = ['Privat', 'Arbeit', 'Verein', 'Nachbarschaft'] as const;

export const DEMO_ACCOUNTS = ['A-demo-lokal', 'A-demo-cloud'] as const;

const MAIL_LABELS = ['home', 'work', 'other'] as const;
const TEL_LABELS = ['mobile', 'home', 'work', 'main'] as const;

function wert(id: string, position: number, label: string | null,
  value: string | null, extra: Record<string, unknown> = {}): LabeledValue {
  return {
    id, position, label_raw: label, label_normalized: label, value, extra,
  };
}

interface Bauplan {
  index: number;
  given: string;
  family: string;
  org: string | null;
  roles: string[];
  accounts: string[];
  mails: number;
  phones: number;
  addresses: number;
  leer: boolean;
  meCard: boolean;
  langerName: boolean;
  langeNotiz: boolean;
  notizGesperrt: boolean;
}

function bauplan(i: number): Bauplan {
  const given = VORNAMEN[i % VORNAMEN.length];
  const family = NACHNAMEN[Math.floor(i / VORNAMEN.length) % NACHNAMEN.length];
  return {
    index: i,
    given,
    family,
    org: ORGANISATIONEN[i % ORGANISATIONEN.length],
    roles: i % 7 === 0 ? [ROLLEN[i % ROLLEN.length]]
      : i % 11 === 0 ? [ROLLEN[0], ROLLEN[1]] : [],
    accounts: i % 13 === 0 ? [...DEMO_ACCOUNTS] : [DEMO_ACCOUNTS[i % 2]],
    mails: i % 5 === 4 ? 3 : i % 3 === 0 ? 0 : 1,
    phones: i % 4 === 3 ? 2 : 1,
    addresses: i % 6 === 5 ? 2 : i % 2 === 0 ? 1 : 0,
    leer: i % 97 === 42,
    meCard: i === 1,
    langerName: i === 7,
    langeNotiz: i === 12,
    notizGesperrt: i % 2 === 0,
  };
}

function anzeigeName(b: Bauplan): string {
  if (b.langerName) {
    return `${b.given}-Annegret Charlotte Wilhelmine `
      + `${b.family}-Überlangenbergerhausen von und zu Testfeld`;
  }
  return `${b.given} ${b.family}`;
}

/** Deterministische Zusammenfassungen, sortiert nach Nachname. */
export function syntheticSummaries(n: number): ContactSummary[] {
  const liste: ContactSummary[] = [];
  for (let i = 0; i < n; i += 1) {
    const b = bauplan(i);
    liste.push({
      id: `demo-${i}`,
      display_name: anzeigeName(b),
      organization_name: b.leer ? null : b.org,
      contact_type: 'person',
      is_me_card: b.meCard,
      field_completeness: b.leer ? 'partial' : 'complete',
      sync_state: 'in_sync',
      conflict_state: null,
      roles: b.roles,
      account_refs: b.accounts,
      email_count: b.leer ? 0 : b.mails,
      phone_count: b.leer ? 0 : b.phones,
      address_count: b.leer ? 0 : b.addresses,
      has_unavailable_fields: b.notizGesperrt,
    });
  }
  return sortiereKontakte(liste);
}

function mailAdresse(b: Bauplan, pos: number): string {
  const basis = `${b.given}.${b.family}`.toLowerCase()
    .replace(/[^a-z0-9.]/g, (z) => ({ ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' }[z] ?? ''));
  return pos === 0 ? `${basis}@example.invalid`
    : `${basis}.${pos}@beispiel.invalid`;
}

function telefon(b: Bauplan, pos: number): string {
  // +49 000 ist kein vergebener Ortsnetzbereich.
  return `+49 000 ${String(1000000 + b.index * 10 + pos).slice(0, 7)}`;
}

/** Deterministisches Detail zu einer `demo-<n>`-Kennung. */
export function syntheticDetail(id: string): ContactDetail {
  const i = Number(id.replace('demo-', ''));
  const b = bauplan(i);
  const leerFaktor = b.leer ? 0 : 1;
  const emails = Array.from({ length: b.mails * leerFaktor }, (_, p) =>
    wert(`${id}-m${p}`, p, MAIL_LABELS[p % MAIL_LABELS.length], mailAdresse(b, p)));
  const phones = Array.from({ length: b.phones * leerFaktor }, (_, p) =>
    wert(`${id}-t${p}`, p, TEL_LABELS[(b.index + p) % TEL_LABELS.length], telefon(b, p)));
  const adressen = Array.from({ length: b.addresses * leerFaktor }, (_, p) =>
    wert(`${id}-a${p}`, p, p === 0 ? 'home' : 'work', null, {
      street: p === 0 ? `Übungsstraße ${1 + (b.index % 140)}\nHinterhaus, 3. Etage` : `Musterallee ${2 + (b.index % 90)}`,
      postal_code: String(10000 + (b.index % 89999)),
      city: p === 0 ? 'Beispielstadt' : 'Probedorf an der Testach',
      country: 'Deutschland',
    }));
  return {
    id,
    workspace_id: 'demo',
    display_name: anzeigeName(b),
    contact_type: 'person',
    given_name: b.given,
    middle_name: null,
    family_name: b.langerName
      ? `${b.family}-Überlangenbergerhausen von und zu Testfeld` : b.family,
    nickname: i % 9 === 0 ? `${b.given.slice(0, 2)}i` : null,
    organization_name: b.leer ? null : b.org,
    department_name: b.org && i % 10 === 1 ? 'Abteilung für erfundene Angelegenheiten' : null,
    job_title: b.org && i % 5 === 1 ? 'Referenzfigur' : null,
    is_me_card: b.meCard,
    birthday_year: i % 8 === 2 ? 1980 + (i % 20) : null,
    birthday_month: i % 8 === 2 ? 1 + (i % 12) : null,
    birthday_day: i % 8 === 2 ? 1 + (i % 28) : null,
    local_revision: 1,
    sync_state: 'in_sync',
    conflict_state: null,
    field_completeness: b.leer ? 'partial' : 'complete',
    updated_at: '2026-08-02T00:00:00Z',
    thumbnail_blob_ref: null,
    emails,
    phones,
    postal_addresses: adressen,
    urls: i % 12 === 6
      ? [wert(`${id}-u0`, 0, 'homepage', 'https://beispiel.invalid/profil')] : [],
    dates: [],
    social_profiles: [],
    instant_messages: [],
    relations: [],
    roles: b.roles,
    field_availability: [{
      field_name: 'note',
      state: b.notizGesperrt ? 'unavailable_by_capability'
        : b.langeNotiz ? 'present' : 'absent',
    }],
    account_refs: b.accounts,
    container_refs: ['C-demo-1'],
    provider_type: 'apple_contacts',
    writable: !b.meCard,
    revision: `rev-demo-${i}`,
    unified_read_only: false,
  };
}

/** Die lange Demo-Notiz (nur wo `field_availability` sie als vorhanden meldet). */
export function syntheticNote(id: string): string | null {
  const i = Number(id.replace('demo-', ''));
  if (!bauplan(i).langeNotiz) return null;
  return 'Synthetische Notiz für Layouttests.\n\n'
    + Array.from({ length: 12 }, (_, z) =>
      `Zeile ${z + 1}: Dieser Text ist erfunden und dient allein dazu, `
      + 'Umbruch, Scrollen und Abstände langer Notizen zu prüfen.').join('\n');
}

export function syntheticKategorien(kontakte: ContactSummary[]): RoleCount[] {
  const zaehler = new Map<string, number>();
  for (const k of kontakte) {
    for (const r of k.roles) zaehler.set(r, (zaehler.get(r) ?? 0) + 1);
  }
  return [...zaehler.entries()]
    .map(([role, count]) => ({ role, count }))
    .sort((a, z) => a.role.localeCompare(z.role, 'de'));
}

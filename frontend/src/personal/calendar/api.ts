// API-Client des Kalendermoduls.
//
// Nutzt bewusst den bestehenden Basis-Client (`getBase`, `authHeaders`) statt
// eines zweiten Transportwegs. Es gibt keinen direkten Provider- oder
// Sidecar-Aufruf aus dem Frontend.
//
// v1 liest. Es gibt hier keine Funktion, die einen Termin anlegen, ändern oder
// löschen könnte — und das ist keine Auslassung, sondern der Vertrag.

import { getBase, authHeaders } from '../../lib/api';

const PREFIX = '/v1/personal/calendar';

export type AutorisierungsStatus =
  | 'not_determined' | 'restricted' | 'denied'
  | 'full_access' | 'write_only' | 'unknown';

export interface Faehigkeiten {
  can_read: boolean;
  can_create_events: boolean;
  can_update_events: boolean;
  can_delete_events: boolean;
  supports_recurrence: boolean;
  supports_attendees: boolean;
  supports_alarms: boolean;
  supports_time_zones: boolean;
  window_required: boolean;
  change_feed: string;
}

export interface ModulStatus {
  bridge_available: boolean;
  authorization_status: AutorisierungsStatus;
  can_read: boolean;
  capabilities: Faehigkeiten;
  detail: string;
  default_window: { past_days: number; future_days: number };
}

export interface KalenderZeile {
  id: string;
  provider_account_id: string;
  provider_calendar_id: string;
  display_name: string;
  calendar_type: string;
  source_identifier: string | null;
  source_title: string | null;
  source_type: string | null;
  color: string | null;
  /** Provider-Wahrheit. Die Oberfläche überstimmt sie nie. */
  is_writable: boolean;
  is_subscribed: boolean;
  is_immutable: boolean;
  supports_events: boolean;
  sync_enabled: boolean;
}

export interface Teilnehmer {
  raw_address: string | null;
  display_name: string | null;
  role: string;
  participant_status: string;
  participant_type: string;
  is_organizer: boolean;
  is_current_user: boolean;
  contact_id: string | null;
}

export interface Termin {
  id: string;
  calendar_id: string;
  title: string | null;
  notes: string | null;
  location: string | null;
  url: string | null;
  starts_at_utc: string;
  ends_at_utc: string;
  /** `null` heisst **schwebend** — nicht „unbekannt" und nicht UTC. */
  time_zone: string | null;
  is_all_day: boolean;
  status: string;
  availability: string;
  recurrence_rule: Record<string, unknown> | null;
  is_detached: boolean;
  occurrence_start_utc: string | null;
  has_alarms: boolean;
  alarms: { absolute_date: string | null; relative_offset_seconds: number | null }[];
  has_attendees: boolean;
  attendees: Teilnehmer[];
  calendar_name: string;
  calendar_color: string | null;
  calendar_is_writable: boolean;
}

export interface TerminFenster {
  events: Termin[];
  count: number;
  window: { start_utc: string; end_utc: string };
  /** Klebt der Bestand am Limit, KANN etwas fehlen. Ehrlichkeit vor Schönheit. */
  truncated: boolean;
}

export interface KalenderLaufErgebnis {
  provider_calendar_id: string;
  complete: boolean;
  /** `false` heisst nicht „nichts gelöscht", sondern „nicht entscheidbar". */
  deletions_derivable: boolean;
  events_seen: number;
  created: number;
  updated: number;
  unchanged: number;
  tombstoned: number;
  error: string | null;
}

export interface LaufBericht {
  run_id: string;
  outcome: 'completed' | 'partial' | 'failed';
  window: { start_utc: string; end_utc: string };
  window_changed: boolean;
  calendars_total: number;
  calendars_complete: number;
  events_seen: number;
  created: number;
  updated: number;
  unchanged: number;
  tombstoned: number;
  calendars: KalenderLaufErgebnis[];
  error: string | null;
}

async function hole<T>(pfad: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${PREFIX}${pfad}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    // Kein Fehlertext des Servers wird durchgereicht: er koennte einen
    // Termininhalt tragen. Die Statusklasse genuegt der Oberflaeche.
    throw new Error(`calendar_api_${res.status}`);
  }
  return (await res.json()) as T;
}

export function ladeStatus(): Promise<ModulStatus> {
  return hole<ModulStatus>('/status');
}

export function pruefeBridge(): Promise<{ bridge_available: boolean;
  authorization_status: AutorisierungsStatus; detail: string }> {
  return hole('/bridge/check', { method: 'POST' });
}

/** Öffnet den Systemdialog. Ausschliesslich auf ausdrückliche Nutzeraktion. */
export function frageBerechtigungAn(): Promise<{
  granted: boolean;
  authorization_status: AutorisierungsStatus;
  /** `false`: der Status war bereits entschieden, macOS zeigt keinen Dialog. */
  prompt_attempted: boolean;
}> {
  return hole('/authorization', {
    method: 'POST',
    body: JSON.stringify({ user_initiated: true }),
  });
}

export function ladeKalender(): Promise<{ calendars: KalenderZeile[]; count: number }> {
  return hole('/calendars');
}

export function ladeTermine(startUtc: string, endeUtc: string,
                            kalenderIds?: string[]): Promise<TerminFenster> {
  const params = new URLSearchParams({ start_utc: startUtc, end_utc: endeUtc });
  for (const id of kalenderIds ?? []) params.append('calendar_ids', id);
  return hole(`/events?${params.toString()}`);
}

/** Ein Lauf. Wird nie automatisch ausgelöst. */
export function synchronisiere(pastDays: number,
                               futureDays: number): Promise<LaufBericht> {
  return hole('/sync', {
    method: 'POST',
    body: JSON.stringify({ past_days: pastDays, future_days: futureDays }),
  });
}

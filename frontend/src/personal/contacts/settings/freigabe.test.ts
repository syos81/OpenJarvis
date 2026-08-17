// Der Weg der Einzelfreigabe.
//
// Zwei Aussagen, die hier bewiesen werden und nicht behauptet:
// der Beleg entsteht **vor** der Route, und was die Fläche zeigt, ist
// mechanisch dasselbe, was der Beleg bindet.

import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { PreparedMutation } from '../api';

const invoke = vi.fn();
const approve = vi.fn();

vi.mock('@tauri-apps/api/core', () => ({ invoke: (...a: unknown[]) => invoke(...a) }));
vi.mock('../../../lib/api', () => ({ isTauri: () => true }));
vi.mock('../api', async () => {
  const echt = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...echt,
    approveMutation: (...a: unknown[]) => approve(...a),
  };
});

const { freigeben, fehlerText, FreigabeAbgelehnt } = await import('./freigabe');
const { ContactsApiError } = await import('../api');

const VORGANG = {
  mutation_id: 'm-1',
  approval_id: 'a-1',
  state: 'awaiting_approval',
  payload_digest: 'a'.repeat(64),
  preview_digest: 'c'.repeat(64),
  reused: false,
  command: 'create',
  target_contact_id: null,
  container_ref: 'C-1',
  container_type: 'cardDAV',
  container_name: 'iCloud',
  container_contact_count: 114,
  target_label: null,
  changes: [],
  warnings: [],
} satisfies PreparedMutation;

beforeEach(() => {
  invoke.mockReset();
  approve.mockReset();
});

describe('Einzelfreigabe', () => {
  it('belegt zuerst und ruft erst danach die Route', async () => {
    const reihenfolge: string[] = [];
    invoke.mockImplementation(async () => {
      reihenfolge.push('beleg');
      return { written: true, reason_code: null };
    });
    approve.mockImplementation(async () => {
      reihenfolge.push('route');
      return {};
    });

    await freigeben({ ...VORGANG }, 'lukas');

    expect(reihenfolge).toEqual(['beleg', 'route']);
  });

  it('bindet genau die Digests des angezeigten Vorgangs', async () => {
    invoke.mockResolvedValue({ written: true, reason_code: null });
    approve.mockResolvedValue({});

    await freigeben({ ...VORGANG }, 'lukas');

    expect(invoke).toHaveBeenCalledWith('personal_contacts_attest_owner_approval', {
      mutationId: 'm-1',
      payloadDigest: 'a'.repeat(64),
      previewDigest: 'c'.repeat(64),
    });
  });

  it('ruft die Route nicht, wenn der Beleg scheitert', async () => {
    invoke.mockResolvedValue({ written: false, reason_code: 'invalid_binding' });

    await expect(freigeben({ ...VORGANG }, 'lukas')).rejects.toBeInstanceOf(
      FreigabeAbgelehnt);
    expect(approve).not.toHaveBeenCalled();
  });

  it('erklaert eine inzwischen veraenderte Vorschau statt sie zu verschweigen', async () => {
    invoke.mockResolvedValue({ written: true, reason_code: null });
    approve.mockRejectedValue(new ContactsApiError(
      403, 'owner_attestation_missing', 'abgelehnt'));

    const fehler = await freigeben({ ...VORGANG }, 'lukas').catch((e) => e);

    expect(fehler.grund).toBe('preview_changed');
    const satz = fehlerText(fehler.grund);
    expect(satz).toContain('geändert');
    expect(satz).toContain('erneut');
    // Und die Beruhigung, ohne die jeder Abbruch nach Datenverlust aussieht.
    expect(satz).toContain('nichts übertragen');
  });

  it('nennt jeden Fehlergrund in ganzen Saetzen', () => {
    for (const grund of ['preview_changed', 'attestation_unavailable',
                         'attestation_failed', 'approval_failed'] as const) {
      const satz = fehlerText(grund);
      expect(satz.length).toBeGreaterThan(30);
      expect(satz).not.toContain('_');
    }
  });
});

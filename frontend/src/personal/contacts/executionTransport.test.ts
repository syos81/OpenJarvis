// @vitest-environment jsdom
//
// Transportschicht des App-Prozess-Kanals — kontaktfrei, ohne Netz.
//
// Was hier bewiesen wird, ist vor allem, was das Frontend **nicht** tut:
// keine Digests rechnen, keinen Bericht deuten, keinen Tauri-Aufruf
// wiederholen. Alle Antworten sind Attrappen; es gibt weder Backend noch
// App-Prozess.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('./api', async () => {
  const echt = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...echt,
    claimAppExecution: vi.fn(),
    settleAppExecution: vi.fn(),
  };
});

import * as api from './api';
import {
  TransportFehler,
  fuehreAus,
  wiederholeSettle,
} from './data/executionTransport';
import type { ExecutionOrderV1, ExecutionReportV1 } from './data/executionTransport';

const mock = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const MUTATION = '1'.repeat(36);

const AUFTRAG: ExecutionOrderV1 = {
  schema_version: 1,
  operation_id: '0'.repeat(36),
  mutation_id: MUTATION,
  claim_token: 'a'.repeat(64),
  operation_type: 'create',
  payload_digest: 'b'.repeat(64),
  preview_digest: 'c'.repeat(64),
  canonical_payload: { fields: { given_name: 'Testperson' } },
  readback_requirements: { required: true, keys: 'field_contract_v1' },
  issued_at: '2026-08-03T00:00:00+00:00',
  expires_at: '2026-08-03T00:10:00+00:00',
  mutation_contract_version: 1,
  field_contract_version: 1,
  transaction_author: 'de.kluender.jarvis.contacts-bridge',
  expected_revision: null,
  provider_target: { container_identifier: 'C1' },
};

const BERICHT: ExecutionReportV1 = {
  schema_version: 1,
  operation_id: AUFTRAG.operation_id,
  mutation_id: MUTATION,
  operation_type: 'create',
  outcome: 'not_sent',
  send_attempted: false,
  save_request_count: 0,
  readback_status: 'not_attempted',
  provider_identifier_digest: null,
  readback_revision: null,
  readback_digest: null,
  error_class: 'provider_channel_disabled_before_send',
  error_digest: null,
  diagnostic_artifact_present: false,
  provider_completed_at: null,
};

interface Aufruf { url: string; body: unknown }

/**
 * Der Transportcode **ohne Kommentare**.
 *
 * Die Kommentare nennen `localStorage` und die Zustandsnamen absichtlich —
 * als Verbot. Eine Verbotspruefung, die daran scheitert, bestraft die
 * Dokumentation statt die Implementierung.
 */
async function nurCode(): Promise<string> {
  const fs = await import('node:fs');
  const path = await import('node:path');
  // In jsdom traegt `import.meta.url` kein file:-Schema; der Pfad wird
  // deshalb ueber das Arbeitsverzeichnis gebildet (vitest laeuft in
  // `frontend/`).
  const roh = fs.readFileSync(
    path.join(process.cwd(),
              'src/personal/contacts/data/executionTransport.ts'), 'utf8');
  return roh
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .filter((z) => !z.trimStart().startsWith('//'))
    .join('\n');
}

function claimLiefert(auftrag: ExecutionOrderV1 | Error): void {
  if (auftrag instanceof Error) mock.claimAppExecution.mockRejectedValue(auftrag);
  else mock.claimAppExecution.mockResolvedValue(auftrag);
}

function settleLiefert(ergebnis: unknown | Error): void {
  if (ergebnis instanceof Error) mock.settleAppExecution.mockRejectedValue(ergebnis);
  else mock.settleAppExecution.mockResolvedValue(ergebnis);
}

const SETTLE_OK = {
  mutation_id: MUTATION, state: 'failed_before_send', outcome: 'failed',
  error_class: null, idempotent: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('Transport: Claim → App-Prozess → Settle', () => {
  it('reicht den Auftrag unverändert weiter und meldet den Bericht', async () => {
    claimLiefert(AUFTRAG);
    settleLiefert(SETTLE_OK);

    const ergebnis = await fuehreAus(MUTATION);

    expect(mock.claimAppExecution).toHaveBeenCalledWith(MUTATION);
    expect(mock.settleAppExecution).toHaveBeenCalledTimes(1);
    const [gemeldeteId, token, bericht] = mock.settleAppExecution.mock.calls[0];
    // Der Token wandert zurück, der Bericht unverändert.
    expect(gemeldeteId).toBe(MUTATION);
    expect(token).toBe(AUFTRAG.claim_token);
    expect(bericht).toMatchObject({ operation_id: AUFTRAG.operation_id });
    expect(ergebnis.settle?.state).toBe('failed_before_send');
    expect(ergebnis.offenesSettle).toBeNull();
  });

  it('berechnet niemals selbst einen Digest', async () => {
    const quelle = await nurCode();
    for (const verboten of ['sha256', 'createHash', 'digest_of', 'canonical_json',
                            'crypto.subtle']) {
      expect(quelle).not.toContain(verboten);
    }
  });

  it('entscheidet keinen Terminalzustand selbst', async () => {
    const quelle = await nurCode();
    // Zustandsnamen gehören dem Kern; der Transport nennt sie nicht.
    for (const zustand of ['succeeded', 'outcome_unknown =', 'failed_before_send =',
                           'provider_applied_pending_reconcile']) {
      expect(quelle).not.toContain(zustand);
    }
  });

  it('wiederholt den Tauri-Aufruf nach einem Fehler nicht', async () => {
    claimLiefert(AUFTRAG);
    const invoke = vi.fn(async () => { throw new Error('App weg'); });
    // `isTauri()` prüft genau dieses Fenstermerkmal; ohne das liefe der
    // Test am Tauri-Pfad vorbei und bewiese nichts.
    (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = { invoke };
    vi.doMock('@tauri-apps/api/core', () => ({ invoke }));

    try {
      await expect(fuehreAus(MUTATION)).rejects.toBeInstanceOf(TransportFehler);
      expect(invoke.mock.calls.length).toBeLessThanOrEqual(1);
    } finally {
      delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__;
      vi.doUnmock('@tauri-apps/api/core');
    }
  });

  it('enthält keine Wiederholungsschleife um den App-Prozess', async () => {
    const quelle = await nurCode();
    // Bewusst eng: `send_attempted` ist ein Vertragsfeld, keine Schleife.
    for (const verboten of ['for (', 'while (', 'setTimeout', 'setInterval',
                            'retry', 'Retry', 'erneutVersuchen']) {
      expect(quelle, verboten).not.toContain(verboten);
    }
    // `executeInAppProcess` kommt genau einmal im Ablauf vor.
    const aufrufe = quelle.split('executeInAppProcess(').length - 1;
    expect(aufrufe).toBeLessThanOrEqual(2);   // Definition + eine Aufrufstelle
  });

  it('hält bei fehlgeschlagenem Settle den Bericht für genau diese Wiederholung', async () => {
    claimLiefert(AUFTRAG);
    settleLiefert(new Error('Backend weg'));

    const ergebnis = await fuehreAus(MUTATION);

    expect(ergebnis.settle).toBeNull();
    expect(ergebnis.offenesSettle).not.toBeNull();
    expect(ergebnis.offenesSettle?.claimToken).toBe(AUFTRAG.claim_token);

    // Die Wiederholung schickt exakt denselben Bericht — und keinen Claim.
    mock.claimAppExecution.mockClear();
    settleLiefert({ ...SETTLE_OK, idempotent: true });
    const nochmal = await wiederholeSettle(ergebnis.offenesSettle!);
    expect(nochmal.idempotent).toBe(true);
    expect(mock.claimAppExecution).not.toHaveBeenCalled();
  });

  it('legt keinen rohen Claim-Token dauerhaft ab', async () => {
    const quelle = await nurCode();
    for (const speicher of ['localStorage', 'sessionStorage', 'indexedDB',
                            'document.cookie']) {
      expect(quelle).not.toContain(speicher);
    }
  });

  it('liefert ausserhalb von Tauri einen ehrlichen not_sent-Bericht', async () => {
    claimLiefert(AUFTRAG);
    settleLiefert(SETTLE_OK);
    const ergebnis = await fuehreAus(MUTATION);
    const gemeldet = mock.settleAppExecution.mock.calls[0][2] as ExecutionReportV1;
    expect(gemeldet.outcome).toBe('not_sent');
    expect(gemeldet.send_attempted).toBe(false);
    expect(gemeldet.error_class).toBe('provider_channel_disabled_before_send');
    expect(ergebnis.bericht?.save_request_count).toBe(0);
  });

  it('bricht vor dem Auftrag folgenlos ab', async () => {
    claimLiefert(new Error('gesperrt'));
    await expect(fuehreAus(MUTATION)).rejects.toThrow();
    // Kein Settle — es wurde nichts beansprucht.
    expect(mock.settleAppExecution).not.toHaveBeenCalled();
  });
});

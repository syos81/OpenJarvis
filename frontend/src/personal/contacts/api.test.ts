// API-Client des Kontakte-Moduls.
//
// Der zentrale Nachweis: **jeder** Aufruf geht über /v1/personal/contacts.
// Es gibt keinen Weg vom Frontend zum Sidecar, zur Bridge oder zu Apple
// Contacts — jede Mutation läuft über den Server und dort über den
// ApplicationCommandBus.
//
// Läuft ohne jsdom (Repo-Konvention, siehe src/lib/api.auth.test.ts): der
// localStorage wird per Stub gestellt, `fetch` gemockt.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const SETTINGS_KEY = 'openjarvis-settings';

class MemoryStorage {
  private store = new Map<string, string>();
  getItem(k: string): string | null {
    return this.store.has(k) ? (this.store.get(k) as string) : null;
  }
  setItem(k: string, v: string): void { this.store.set(k, String(v)); }
  removeItem(k: string): void { this.store.delete(k); }
  clear(): void { this.store.clear(); }
}

interface Aufruf { url: string; init: RequestInit }

let aufrufe: Aufruf[] = [];

function antworte(body: unknown, status = 200): void {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    aufrufe.push({ url, init });
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as unknown as Response;
  }));
}

beforeEach(() => {
  aufrufe = [];
  vi.resetModules();
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'test-anon-key');
  const storage = new MemoryStorage();
  storage.setItem(SETTINGS_KEY, JSON.stringify({
    apiUrl: 'http://localhost:8000', apiKey: 'geheim',
  }));
  (globalThis as unknown as { localStorage: MemoryStorage }).localStorage = storage;
  antworte({});
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  (globalThis as unknown as { localStorage?: MemoryStorage }).localStorage = undefined;
});

const letzter = () => aufrufe[aufrufe.length - 1];
const kopf = () => (letzter().init.headers ?? {}) as Record<string, string>;

// ── Transport ──────────────────────────────────────────────────────────────
describe('Transport', () => {
  it('spricht ausschliesslich den eigenen Serverpfad an', async () => {
    const api = await import('./api');
    antworte({ items: [], next_cursor: null, has_more: false });
    await api.listContacts();
    expect(letzter().url).toBe('http://localhost:8000/v1/personal/contacts');
  });

  it('sendet den Bearer-Token des lokalen Servers mit', async () => {
    const api = await import('./api');
    await api.getCapabilities();
    expect(kopf().Authorization).toBe('Bearer geheim');
  });

  it('sendet den Workspace als Kopfzeile, nie als Query', async () => {
    const api = await import('./api');
    api.setWorkspace('haushalt');
    await api.listContacts();
    expect(kopf()['X-Personal-Workspace']).toBe('haushalt');
    expect(letzter().url).not.toContain('haushalt');
  });

  it('setzt den Content-Type nur bei Anfragen mit Koerper', async () => {
    const api = await import('./api');
    await api.listContacts();
    expect(kopf()['Content-Type']).toBeUndefined();
    await api.assignRole('k-1', 'Mieter');
    expect(kopf()['Content-Type']).toBe('application/json');
  });

  it('maskiert Bezeichner in Pfaden', async () => {
    const api = await import('./api');
    await api.getContact('k/1 böse');
    expect(letzter().url).toContain('k%2F1%20b%C3%B6se');
  });
});

// ── Fehlerabbildung ────────────────────────────────────────────────────────
describe('Fehler', () => {
  it('uebernimmt Code, Status und Wiederholbarkeit aus der Antwort', async () => {
    const api = await import('./api');
    antworte({ detail: { code: 'conflict', message: 'Kollision', retryable: false } }, 409);
    await expect(api.getContact('k-1')).rejects.toMatchObject({
      name: 'ContactsApiError', code: 'conflict', status: 409, retryable: false,
    });
  });

  it('merkt sich wiederholbare Fehler als solche', async () => {
    const api = await import('./api');
    antworte({ detail: { code: 'unavailable', message: 'Kein Leser', retryable: true } }, 503);
    await expect(api.reconcileMutation('m-1')).rejects.toMatchObject({
      code: 'unavailable', retryable: true,
    });
  });

  it('bleibt bei einer Antwort ohne JSON-Koerper aussagefaehig', async () => {
    const api = await import('./api');
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, json: async () => { throw new Error('kein JSON'); },
    } as unknown as Response)));
    await expect(api.listContacts()).rejects.toMatchObject({
      status: 500, code: 'internal',
    });
  });
});

// ── Lesen ──────────────────────────────────────────────────────────────────
describe('Lesen', () => {
  it('reicht Suche, Filter und Seitenmarke als Query durch', async () => {
    const api = await import('./api');
    antworte({ items: [], next_cursor: null, has_more: false });
    await api.listContacts({
      search: 'mül ler', role: 'Mieter', providerAccountId: 'apple',
      cursor: 'abc==', limit: 25,
    });
    const url = letzter().url;
    expect(url).toContain('search=m%C3%BCl%20ler');
    expect(url).toContain('role=Mieter');
    expect(url).toContain('provider_account_id=apple');
    expect(url).toContain('cursor=abc%3D%3D');
    expect(url).toContain('limit=25');
  });

  it('laesst leere Parameter weg statt sie leer zu senden', async () => {
    const api = await import('./api');
    antworte({ items: [], next_cursor: null, has_more: false });
    await api.listContacts({ search: '', role: undefined });
    expect(letzter().url).toBe('http://localhost:8000/v1/personal/contacts');
  });
});

// ── Vorbereiten, nie ausfuehren ────────────────────────────────────────────
describe('Mutationen vorbereiten', () => {
  it('schickt create mit maskierter Containerreferenz, nie mit Apple-Kennung', async () => {
    const api = await import('./api');
    await api.prepareCreate({
      idempotencyKey: 'i-1', correlationId: 'c-1',
      containerRef: 'C-1b3d99', fields: { given_name: 'Neu' },
    });
    expect(letzter().url).toBe('http://localhost:8000/v1/personal/contacts');
    expect(letzter().init.method).toBe('POST');
    expect(JSON.parse(letzter().init.body as string)).toEqual({
      idempotency_key: 'i-1', correlation_id: 'c-1',
      container_ref: 'C-1b3d99', fields: { given_name: 'Neu' },
    });
  });

  it('schickt update mit erwarteter Revision — sonst gaebe es keinen Konfliktschutz', async () => {
    const api = await import('./api');
    await api.prepareUpdate('k-1', {
      idempotencyKey: 'i-2', correlationId: 'c-2', expectedRevision: '7',
      fields: { nickname: 'Kurz' },
    });
    expect(letzter().init.method).toBe('PATCH');
    const body = JSON.parse(letzter().init.body as string);
    expect(body.expected_revision).toBe('7');
    // Das Ziel steht im Pfad, nicht im Koerper — und ist die lokale Kennung.
    expect(letzter().url).toContain('/k-1');
    expect(JSON.stringify(body)).not.toContain('raw-');
  });

  it('zielt beim Loeschen auf die lokale Kennung, nie auf einen Namen', async () => {
    const api = await import('./api');
    await api.prepareDelete('k-1', {
      idempotencyKey: 'i-3', correlationId: 'c-3', expectedRevision: '7',
    });
    expect(letzter().url).toContain('/k-1/delete');
    const body = JSON.parse(letzter().init.body as string);
    expect(body.expected_revision).toBe('7');
    expect(JSON.stringify(body)).not.toContain('display_name');
  });

  it('sendet keine rohe Providerkennung in irgendeinem Mutationskoerper', async () => {
    const api = await import('./api');
    await api.prepareCreate({
      idempotencyKey: 'i-4', correlationId: 'c-4',
      containerRef: 'C-4b8df1', fields: { given_name: 'Neu' },
    });
    const koerper = letzter().init.body as string;
    for (const verboten of ['ABAccount', 'provider_account_id',
                            'container_identifier', 'target_provider_identifier']) {
      expect(koerper).not.toContain(verboten);
    }
  });
});

// ── Ausfuehren: ein eigener, ausdruecklicher Schritt ───────────────────────
describe('Ausfuehren', () => {
  it('verlangt die ausdrueckliche Nutzeraktion im Koerper', async () => {
    const api = await import('./api');
    await api.executeMutation('m-1');
    expect(letzter().url).toContain('/mutations/m-1/execute');
    expect(letzter().init.method).toBe('POST');
    expect(JSON.parse(letzter().init.body as string))
      .toEqual({ user_initiated: true });
  });

  it('traegt die Bestaetigung nie in der URL', async () => {
    const api = await import('./api');
    await api.executeMutation('m-2');
    expect(letzter().url).not.toContain('user_initiated');
    expect(letzter().url).not.toContain('?');
  });
});

// ── Freigaben ──────────────────────────────────────────────────────────────
describe('Freigaben', () => {
  it('nennt bei jeder Entscheidung den entscheidenden Menschen', async () => {
    const api = await import('./api');
    for (const [fn, pfad] of [
      [api.approveMutation, 'approve'], [api.rejectMutation, 'reject'],
      [api.cancelMutation, 'cancel'],
    ] as const) {
      await fn('m-1', 'lukas');
      expect(letzter().url).toContain(`/mutations/m-1/${pfad}`);
      expect(JSON.parse(letzter().init.body as string)).toEqual({
        decision_actor: 'lukas',
      });
    }
  });

  it('markiert Ablauf ohne Entscheider — das war keine Entscheidung', async () => {
    const api = await import('./api');
    await api.expireMutation('m-1');
    expect(letzter().url).toContain('/mutations/m-1/expire');
    expect(letzter().init.body).toBeUndefined();
  });

  it('blendet abgelaufene Freigaben nur auf ausdruecklichen Wunsch aus', async () => {
    const api = await import('./api');
    antworte([]);
    await api.listApprovals();
    expect(letzter().url).not.toContain('include_expired');
    await api.listApprovals({ includeExpired: false });
    expect(letzter().url).toContain('include_expired=false');
  });
});

// ── Abgleich ───────────────────────────────────────────────────────────────
describe('Abgleich', () => {
  it('gleicht ab, ohne einen Koerper zu senden', async () => {
    const api = await import('./api');
    await api.reconcileMutation('m-1');
    expect(letzter().url).toContain('/mutations/m-1/reconcile');
    expect(letzter().init.method).toBe('POST');
    expect(letzter().init.body).toBeUndefined();
  });

  it('bietet keine Funktion zum erneuten Senden an', async () => {
    const api = await import('./api');
    const namen = Object.keys(api);
    // `executeMutation` ist der EINE erlaubte Sendeweg und deshalb hier
    // ausgenommen; alles, was ein zweites Senden nahelegte, bleibt verboten.
    for (const verboten of ['retry', 'resend', 'send', 'force']) {
      expect(namen.filter((n) => n.toLowerCase().includes(verboten))).toEqual([]);
    }
    expect(namen.filter((n) => n.toLowerCase().includes('execute')))
      .toEqual(['executeMutation']);
  });
});

// ═══ Berechtigungsanfrage über den App-Prozess ══════════════════════════════
//
// Der Weg über den Server ist aufgegeben: macOS rechnet einen TCC-Dialog dem
// verantwortlichen Prozess zu, und der Sidecar wird über `uv` und `python`
// erreicht — beides ohne App-Bundle. `requestAccess` kam von dort mit
// `CNErrorDomain/100` zurück, ohne dass je ein Dialog erschien.
describe('Berechtigungsanfrage', () => {
  const invoke = vi.fn();
  //: PII-arme Laufzeitdiagnostik, die das native Kommando mitliefert.
  const DIAG = {
    bundle_identifier: 'de.kluender.jarvis',
    has_usage_description: true,
    app_active: true,
    called_on_main_thread: true,
    entity_type: 0,
    status_before: 'notDetermined' as const,
    callback_ran: true,
    callback_count: 1,
  };

  async function ladeApi(inTauri: boolean) {
    vi.resetModules();
    vi.doMock('../../lib/api', async () => {
      const echt = await vi.importActual<typeof import('../../lib/api')>('../../lib/api');
      return { ...echt, isTauri: () => inTauri };
    });
    vi.doMock('@tauri-apps/api/core', () => ({ invoke }));
    return import('./api');
  }

  beforeEach(() => { invoke.mockReset(); });
  afterEach(() => { vi.doUnmock('../../lib/api'); vi.doUnmock('@tauri-apps/api/core'); });

  it('ruft das Kommando des App-Prozesses, nicht den Server', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'authorized', granted: true, prompt_attempted: true,
      error_domain: null, error_code: null, ...DIAG,
    });

    const sicht = await api.requestAuthorization();

    expect(invoke).toHaveBeenCalledExactlyOnceWith(
      'personal_contacts_request_authorization');
    expect(sicht.status).toBe('authorized');
    // Kein HTTP-Aufruf: der Server ist an dieser Stelle nicht beteiligt.
    expect(aufrufe).toEqual([]);
  });

  it('fuehrt notDetermined nach denied korrekt weiter', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'denied', granted: false, prompt_attempted: true,
      error_domain: null, error_code: null, ...DIAG,
    });
    const sicht = await api.requestAuthorization();
    expect(sicht.status).toBe('denied');
    expect(sicht.can_request).toBe(false);
  });

  it('traegt die Laufzeitdiagnostik in der Kennung', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'notDetermined', granted: false, prompt_attempted: true,
      error_domain: 'CNErrorDomain', error_code: 100, ...DIAG,
    });
    const fehler = await api.requestAuthorization().catch((e) => e);
    for (const teil of ['bundle=de.kluender.jarvis', 'usage=true',
                        'active=true', 'mainthread=true', 'entity=0',
                        'callback=true/1']) {
      expect(fehler.technicalCode).toContain(teil);
    }
    // Trotzdem kein Pfad und kein Systemfreitext.
    expect(fehler.technicalCode).not.toMatch(/\/Users\//);
    expect(fehler.technicalCode).not.toMatch(/\.app/);
  });

  it('haelt Apple-Domain und Fehlercode in der Kennung fest', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'notDetermined', granted: false, prompt_attempted: true,
      error_domain: 'CNErrorDomain', error_code: 100, ...DIAG,
    });
    await expect(api.requestAuthorization()).rejects.toMatchObject({
      code: 'unavailable',
      retryable: true,
    });
    const f = await api.requestAuthorization().catch((e) => e);
    expect(f.technicalCode).toContain(
      'authorization_request:tcc_request_rejected:CNErrorDomain/100');
  });

  it('unterscheidet den Zeitueberlauf vom Providerfehler', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'notDetermined', granted: false, prompt_attempted: true,
      error_domain: 'timeout', error_code: 0, ...DIAG,
    });
    const f = await api.requestAuthorization().catch((e) => e);
    expect(f.technicalCode).toContain('authorization_request:request_timeout');
  });

  it('sagt im Browser ehrlich, dass es die App braucht', async () => {
    const api = await ladeApi(false);
    await expect(api.requestAuthorization()).rejects.toMatchObject({
      technicalCode: 'tcc_prompt_unavailable:requires_desktop_app',
      retryable: false,
    });
    expect(invoke).not.toHaveBeenCalled();
    expect(aufrufe).toEqual([]);
  });

  it('wiederholt nach einem Fehlschlag nichts von selbst', async () => {
    const api = await ladeApi(true);
    invoke.mockRejectedValue(new Error('IPC weg'));
    await expect(api.requestAuthorization()).rejects.toMatchObject({
      technicalCode: 'tcc_prompt_unavailable:ipc_failed',
    });
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it('gibt keine Kontaktdaten und keinen Pfad weiter', async () => {
    const api = await ladeApi(true);
    invoke.mockResolvedValue({
      status: 'notDetermined', granted: false, prompt_attempted: true,
      error_domain: 'CNErrorDomain', error_code: 100, ...DIAG,
    });
    const fehler = await api.requestAuthorization().catch((e) => e);
    const text = `${fehler.message} ${fehler.technicalCode}`;
    expect(text).not.toMatch(/\/Users\//);
    expect(text).not.toMatch(/\.app/);
    expect(text).not.toMatch(/@/);
  });

  it('der Statusabruf bleibt beim Server', async () => {
    const api = await ladeApi(true);
    antworte({ status: 'notDetermined', can_request: true,
               bridge_available: true, reason: '', technical_code: '' });
    await api.getAuthorization();
    expect(letzter().url).toContain('/v1/personal/contacts/authorization');
    expect(invoke).not.toHaveBeenCalled();
  });
});

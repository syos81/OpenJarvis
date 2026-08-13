// @vitest-environment jsdom
// I · Wenn Schreiben gesperrt ist, darf die Oberfläche nicht so tun, als gäbe
// es Schreiben nicht.
//
// Vorher: `anlegenSichtbar={Boolean(caps?.create_supported)}` — bei
// `channel_mode: disabled` verschwand das Plus spurlos. Wer die Freigabe nicht
// ohnehin kannte, hatte weder einen Hinweis noch einen Weg.
//
// Die harte Grenze prüft dieser Test mit: Jarvis erklärt die Freigabe und
// prüft neu, aber er erteilt sie nie selbst.

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { AppChannelCapabilities, Capabilities } from './api';
import { SchreibsperreDialog, sperrgrund } from './editor/SchreibsperreDialog';

const CAPS = (over: Partial<Capabilities> = {}): Capabilities => ({
  read_supported: true, create_supported: false, update_supported: false,
  delete_supported: false, change_history_supported: true,
  full_diff_supported: true, notes_supported: false,
  unified_read_supported: true, unified_link_supported: false,
  me_card_writable: false, unavailable_fields: [], mutations_available: false,
  ...over,
});

const KANAL = (over: Partial<AppChannelCapabilities> = {}): AppChannelCapabilities => ({
  schema_version: 3, channel: 'app_process', channel_mode: 'disabled',
  native_create_available: true, create_supported: false,
  update_supported: false, delete_supported: false,
  provider_write_enabled: false, architecture: 'arm64', app_version: '1.0.1',
  native_bridge_version: '0', ...over,
});

describe('Sperrgrund', () => {
  it('unterscheidet die fehlende Freigabe vom fehlenden Schreibpfad', () => {
    const ohneFreigabe = sperrgrund(CAPS(), KANAL());
    expect(ohneFreigabe.freigabeHilft).toBe(true);
    expect(ohneFreigabe.text).toContain('keine gültige');

    const ohnePfad = sperrgrund(CAPS(), KANAL({ native_create_available: false }));
    expect(ohnePfad.freigabeHilft).toBe(false);
    // Eine Freigabe würde daran nichts ändern — das gehört gesagt, sonst
    // sucht der Eigentümer an der falschen Stelle.
    expect(ohnePfad.text).toContain('Freigabe würde daran nichts ändern');
  });

  it('nennt die fehlende Brücke als eigene Lage', () => {
    const grund = sperrgrund(CAPS({ read_supported: false }), KANAL());
    expect(grund.freigabeHilft).toBe(false);
    expect(grund.titel).toContain('antwortet nicht');
  });
});

describe('Schreibsperre-Dialog', () => {
  it('nennt Zustand, Datei und Vertrag — und dass die Freigabe dem Eigentümer gehört', () => {
    render(<SchreibsperreDialog caps={CAPS()} kanal={KANAL()} offen
                                onClose={() => {}}
                                onErneutPruefen={async () => {}} />);
    const text = screen.getByTestId('schreibsperre').textContent ?? '';
    expect(text).toContain('contacts-write-release.json');
    expect(text).toContain('contacts-write-v1');
    expect(text).toContain('Jarvis kann und darf');
    // Lesen bleibt möglich — sonst liest sich die Sperre größer, als sie ist.
    expect(text).toContain('Lesen, Suchen');
  });

  it('bietet erneut prüfen an und erzeugt dabei nichts', async () => {
    const pruefen = vi.fn(async () => {});
    render(<SchreibsperreDialog caps={CAPS()} kanal={KANAL()} offen
                                onClose={() => {}} onErneutPruefen={pruefen} />);
    await userEvent.click(screen.getByTestId('schreibsperre-erneut-pruefen'));
    expect(pruefen).toHaveBeenCalledTimes(1);
  });

  it('hat keinen Knopf, der eine Freigabe erteilt', () => {
    render(<SchreibsperreDialog caps={CAPS()} kanal={KANAL()} offen
                                onClose={() => {}}
                                onErneutPruefen={async () => {}} />);
    for (const knopf of screen.getAllByRole('button')) {
      const beschriftung = (knopf.textContent ?? '').toLowerCase();
      expect(beschriftung).not.toContain('freigeben');
      expect(beschriftung).not.toContain('aktivieren');
      expect(beschriftung).not.toContain('erteilen');
    }
  });
});

describe('Die Aktion verschwindet nicht mehr', () => {
  const quelltext = async (datei: string) => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    return fs.readFileSync(path.join(process.cwd(), datei), 'utf8');
  };

  it('rendert das Plus auch ohne Schreibrecht', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsToolbar.tsx');
    // Kein `{anlegenSichtbar && (` mehr: der Knopf steht immer, gesperrt
    // führt er zur Erklärung.
    expect(quelle).not.toContain('{anlegenSichtbar && (');
    expect(quelle).toContain('if (!anlegenMoeglich) { onGesperrt(); return; }');
    expect(quelle).toContain("data-gesperrt=");
  });

  it('führt den gesperrten Klick in den Erklärdialog', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    expect(quelle).toContain('onGesperrt={() => setSperreOffen(true)}');
    expect(quelle).toContain('<SchreibsperreDialog');
  });

  it('holt Fähigkeiten und Kanal beim erneuten Prüfen frisch', async () => {
    const quelle = await quelltext(
      'src/personal/contacts/workspace/ContactsWorkspace.tsx');
    const block = quelle.split('onErneutPruefen={')[1].slice(0, 400);
    expect(block).toContain('quelle.capabilities()');
    expect(block).toContain('quelle.appChannel()');
  });
});

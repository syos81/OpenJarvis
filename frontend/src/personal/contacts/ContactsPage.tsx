// Kontakte — dünner Einstieg der Route `/contacts`.
//
// Die gesamte Oberfläche lebt im dreispaltigen ContactsWorkspace
// (workspace/ContactsWorkspace.tsx); Aufbau und Verträge sind in
// docs/personal-jarvis/contacts-frontend-apple-redesign-2026-08-02.md
// beschrieben. Verbindliche Designreferenz ist die macOS-Kontakte-App auf
// dem M2 Pro; die Pixelabnahme dagegen ist ausdrücklich offen.
//
// Änderungen werden weiterhin immer erst vorbereitet und freigegeben —
// nichts wird ungefragt übertragen. Kein Schritt dieser Oberfläche löst
// von sich aus eine Provideroperation aus.

import './tokens.css';
import { ContactsWorkspace } from './workspace/ContactsWorkspace';

export default function ContactsPage() {
  return <ContactsWorkspace />;
}

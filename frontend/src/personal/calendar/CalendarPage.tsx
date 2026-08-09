// Kalender — dünner Einstieg der Route `/calendar`.
//
// Die gesamte Oberfläche lebt im dreispaltigen CalendarWorkspace. Verbindliche
// Designreferenz ist die Apple-Kalender-App auf dem M2 Pro; die Pixelabnahme
// dagegen ist ausdrücklich offen (Paritätsvertrag §4 der Baseline).
//
// Diese Fassung liest — und lässt daneben einzelfreigegebene Mutationen zu:
// normativ DEC-069 — Kalenderschreiben produktiv zugelassen:
// einzelfreigegebene Mutationen über den getrennten Schreibpfad
// (docs/governance/decisions/DEC-069-kalenderschreiben-einzelfreigabe.md).
// Angelegt wird ein Termin nur über das Terminformular nach ausdrücklicher
// Freigabe; ändern und löschen gibt es weiterhin nicht (P2/P3).

import { CalendarWorkspace } from './CalendarWorkspace';

export default function CalendarPage() {
  return <CalendarWorkspace />;
}

// Kalender — dünner Einstieg der Route `/calendar`.
//
// Die gesamte Oberfläche lebt im dreispaltigen CalendarWorkspace. Verbindliche
// Designreferenz ist die Apple-Kalender-App auf dem M2 Pro; die Pixelabnahme
// dagegen ist ausdrücklich offen (Paritätsvertrag §4 der Baseline).
//
// Diese Fassung liest. Sie legt keinen Termin an, ändert keinen und löscht
// keinen — und deutet das auch nirgends an.

import { CalendarWorkspace } from './CalendarWorkspace';

export default function CalendarPage() {
  return <CalendarWorkspace />;
}

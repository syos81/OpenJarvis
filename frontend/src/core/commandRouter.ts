// Jarvis Core v0 — lokaler Kommandorouter.
//
// Der Router ist bewusst rein: er kennt weder React noch den Store noch ein
// Netzwerk. Eingabe rein, Ergebnis raus, alles synchron und lokal. Genau
// diese Trennung ist die Stelle, an der später eine Planner- oder
// Operator-Funktion andocken kann — sie wird hier nicht vorweggenommen und
// nicht als leerer Rahmen angedeutet.

/** Ein tatsächlich implementiertes lokales Kommando. */
export interface CoreCommand {
  readonly name: string;
  readonly summary: string;
}

/**
 * Die vollständige Liste dessen, was der Core heute kann.
 *
 * `help` liest ausschliesslich aus dieser Liste, damit die Oberfläche keine
 * Fähigkeit behaupten kann, die es nicht gibt.
 */
export const CORE_COMMANDS: readonly CoreCommand[] = [
  { name: 'status', summary: 'Zeigt den lokalen Core-Status.' },
  { name: 'help', summary: 'Listet die lokalen Kommandos.' },
];

/** Die Kopfzeile des Status — der sichtbare Beleg, dass der Core lebt. */
export const CORE_VERSION_LINE = 'Jarvis Core v0 aktiv';

/**
 * Kontext, den die Oberfläche ohne zusätzliche Infrastruktur bereits kennt.
 *
 * Bewusst klein: hier entsteht keine Context-Engine. Was nicht ohnehin
 * vorliegt, wird auch nicht angezeigt.
 */
export interface CoreContext {
  /** Aktive Route der App, z. B. `/calendar`. Fehlt, wenn unbekannt. */
  readonly route?: string;
}

export type CoreResultKind = 'status' | 'help' | 'unknown';

export interface CoreResult {
  readonly kind: CoreResultKind;
  /** Der normalisierte Befehl, auf den geroutet wurde ('' bei leerer Eingabe). */
  readonly command: string;
  /** Die anzuzeigenden Zeilen, in Reihenfolge. */
  readonly lines: readonly string[];
}

const BEKANNTE_BEFEHLE = CORE_COMMANDS.map((c) => c.name).join(', ');

function statusErgebnis(kontext: CoreContext): CoreResult {
  const lines = [CORE_VERSION_LINE];
  const route = kontext.route?.trim();
  // Nur anzeigen, was die Oberfläche ohnehin weiss. Kein Platzhalter, keine
  // erfundene „unbekannt"-Zeile.
  if (route) lines.push(`Aktive Ansicht: ${route}`);
  return { kind: 'status', command: 'status', lines };
}

function helpErgebnis(): CoreResult {
  return {
    kind: 'help',
    command: 'help',
    lines: CORE_COMMANDS.map((c) => `${c.name} — ${c.summary}`),
  };
}

function unbekanntErgebnis(command: string): CoreResult {
  const kopf = command
    ? `Unbekannter Befehl: ${command}`
    : 'Kein Befehl eingegeben.';
  return {
    kind: 'unknown',
    command,
    lines: [kopf, `Bekannte Befehle: ${BEKANNTE_BEFEHLE}.`],
  };
}

/**
 * Routet eine Eingabe auf ein lokales Ergebnis.
 *
 * Total: jede Eingabe — auch die leere — bekommt ein sichtbares Ergebnis.
 * Es gibt keinen Wurf, keinen Fehlerzustand und keine stille Aktion.
 */
export function routeCommand(input: string, kontext: CoreContext = {}): CoreResult {
  const command = input.trim().toLowerCase();
  switch (command) {
    case 'status':
      return statusErgebnis(kontext);
    case 'help':
      return helpErgebnis();
    default:
      return unbekanntErgebnis(command);
  }
}

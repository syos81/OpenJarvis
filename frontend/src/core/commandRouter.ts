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
  { name: 'kontakt', summary: 'Sucht im lokalen Kontaktbestand: kontakt <suchbegriff>' },
  { name: 'termine', summary: 'Zeigt Termine des Tages: termine [heute|morgen|JJJJ-MM-TT]' },
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

export type CoreResultKind = 'status' | 'help' | 'unknown' | 'read';

/**
 * Ein Leseauftrag, den der reine Router nicht selbst ausführen kann.
 *
 * Der Router bleibt synchron und total: er entscheidet, WAS gelesen werden
 * soll, und liefert das als Datum zurück. Ausgeführt wird es eine Schicht
 * höher über den `CoreReadPort`. Damit bleibt der Router die einzige
 * Stelle, die über Kommandos entscheidet — und die einzige Stelle, die
 * niemand mit einem Netzaufruf verwechseln kann.
 */
export type CoreReadRequest =
  | { readonly art: 'kontakte'; readonly query: string; readonly limit: number }
  | { readonly art: 'termine'; readonly tag: string };

export interface CoreResult {
  readonly kind: CoreResultKind;
  /** Der normalisierte Befehl, auf den geroutet wurde ('' bei leerer Eingabe). */
  readonly command: string;
  /** Die anzuzeigenden Zeilen, in Reihenfolge. */
  readonly lines: readonly string[];
  /** Nur bei `kind === 'read'`: was gelesen werden soll. */
  readonly read?: CoreReadRequest;
}

/** Wie viele Kontakttreffer die Bar höchstens anzeigt. Mehrdeutige Suchen
 *  werden dadurch NICHT auf einen Treffer verengt — sie bleiben mehrdeutig
 *  und sagen das auch. */
export const KONTAKT_TREFFER_LIMIT = 10;

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

/** `termine` ohne Argument meint heute; sonst gilt das Argument. */
function terminErgebnis(argument: string): CoreResult {
  const tag = argument.trim().toLowerCase() || 'heute';
  const erlaubt = tag === 'heute' || tag === 'morgen'
    || /^\d{4}-\d{2}-\d{2}$/.test(tag);
  if (!erlaubt) {
    return {
      kind: 'unknown',
      command: 'termine',
      lines: [
        `Unverständlicher Tag: ${tag}`,
        'Erwartet: termine [heute|morgen|JJJJ-MM-TT].',
      ],
    };
  }
  return {
    kind: 'read',
    command: 'termine',
    lines: [`Lese Termine (${tag}) …`],
    read: { art: 'termine', tag },
  };
}

/** `kontakt <suchbegriff>` — ohne Suchbegriff wird NICHT der ganze Bestand
 *  geladen; eine leere Suche ist eine Rückfrage, kein Massenabruf. */
function kontaktErgebnis(argument: string): CoreResult {
  const query = argument.trim();
  if (!query) {
    return {
      kind: 'unknown',
      command: 'kontakt',
      lines: [
        'Kein Suchbegriff angegeben.',
        'Erwartet: kontakt <suchbegriff>.',
      ],
    };
  }
  return {
    kind: 'read',
    command: 'kontakt',
    lines: [`Suche Kontakte zu „${query}" …`],
    read: { art: 'kontakte', query, limit: KONTAKT_TREFFER_LIMIT },
  };
}

/**
 * Routet eine Eingabe auf ein lokales Ergebnis.
 *
 * Total: jede Eingabe — auch die leere — bekommt ein sichtbares Ergebnis.
 * Es gibt keinen Wurf, keinen Fehlerzustand und keine stille Aktion.
 *
 * Der Router bleibt rein und synchron. Lesebefehle liefern einen
 * `read`-Deskriptor statt Daten; ausgeführt wird er über den Lese-Port.
 */
export function routeCommand(input: string, kontext: CoreContext = {}): CoreResult {
  const roh = input.trim();
  const trenner = roh.indexOf(' ');
  // Nur das Kommando wird normalisiert; das Argument behält seine
  // Schreibweise, damit ein Suchbegriff unverfälscht angezeigt wird.
  const command = (trenner === -1 ? roh : roh.slice(0, trenner)).toLowerCase();
  const argument = trenner === -1 ? '' : roh.slice(trenner + 1);
  switch (command) {
    case 'status':
      return statusErgebnis(kontext);
    case 'help':
      return helpErgebnis();
    case 'kontakt':
      return kontaktErgebnis(argument);
    case 'termine':
      return terminErgebnis(argument);
    default:
      // Die unbekannte Eingabe wird VOLLSTÄNDIG zurückgemeldet, nicht nur
      // ihr erstes Wort: wer „mach mal was" eingibt, muss genau das
      // wiederfinden. (Bestehendes Verhalten — die Zerlegung in Kommando
      // und Argument oben darf es nicht verkürzen.)
      return unbekanntErgebnis(roh.toLowerCase());
  }
}

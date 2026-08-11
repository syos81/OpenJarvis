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
  // Schreibende Kommandos. Jedes BEREITET nur vor — ausgeführt wird
  // ausschliesslich über `freigabe <id>`. Ein Kalender-Löschen gibt es
  // hier bewusst nicht.
  { name: 'kontakt-neu', summary: 'Bereitet einen neuen Kontakt vor: kontakt-neu <container> | <Vorname Nachname>' },
  { name: 'kontakt-aendern', summary: 'Bereitet eine Änderung vor: kontakt-aendern <suchbegriff> | <feld> = <wert>' },
  { name: 'kontakt-loeschen', summary: 'Bereitet eine Löschung vor: kontakt-loeschen <suchbegriff>' },
  { name: 'termin-neu', summary: 'Bereitet einen Termin vor: termin-neu <kalender> | <tag> | <HH:MM-HH:MM> | <titel>' },
  { name: 'termin-aendern', summary: 'Bereitet eine Titeländerung vor: termin-aendern <tag> | <suchbegriff> | <neuer titel>' },
  { name: 'freigabe', summary: 'Gibt EINE vorbereitete Mutation frei und führt sie aus: freigabe <id>' },
  { name: 'abbrechen', summary: 'Verwirft die vorbereitete Mutation ohne Ausführung.' },
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

export type CoreResultKind =
  'status' | 'help' | 'unknown' | 'read' | 'write_prepare' | 'write_execute';

/**
 * Ein Schreibauftrag, den der reine Router nicht selbst ausführt.
 *
 * Wie beim Lesen entscheidet der Router nur, WAS geschehen soll. Der
 * entscheidende Unterschied: ein `write`-Auftrag mit `phase: 'prepare'`
 * mutiert NICHTS — er holt eine Vorschau. Erst ein Auftrag mit
 * `phase: 'execute'`, den ausschliesslich das Kommando `freigabe` erzeugen
 * kann, führt aus. Beides sind getrennte Eingaben des Eigentümers; es gibt
 * keinen Pfad, auf dem eine Suche oder eine Anzeige das Zweite auslöst.
 */
export type CoreWriteRequest =
  | { readonly phase: 'prepare'; readonly operation: 'kontakt_anlegen';
      readonly ziel: string; readonly name: string }
  | { readonly phase: 'prepare'; readonly operation: 'kontakt_aendern';
      readonly query: string; readonly feld: string; readonly wert: string }
  | { readonly phase: 'prepare'; readonly operation: 'kontakt_loeschen';
      readonly query: string }
  | { readonly phase: 'prepare'; readonly operation: 'termin_anlegen';
      readonly ziel: string; readonly tag: string; readonly vonBis: string;
      readonly titel: string }
  | { readonly phase: 'prepare'; readonly operation: 'termin_aendern';
      readonly tag: string; readonly query: string; readonly neuerTitel: string }
  | { readonly phase: 'execute'; readonly mutationId: string }
  | { readonly phase: 'abort' };

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
  /** Nur bei den Schreibarten: was vorbereitet bzw. ausgeführt werden soll. */
  readonly write?: CoreWriteRequest;
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


// ── Schreibbefehle: sie BEREITEN VOR, sie fuehren nicht aus ────────────────

/** Zerlegt an `|` und liefert die getrimmten Teile. */
function teile(argument: string): string[] {
  return argument.split('|').map((t) => t.trim());
}

function fehlform(command: string, erwartet: string): CoreResult {
  return {
    kind: 'unknown',
    command,
    lines: ['Eingabe nicht verstanden.', `Erwartet: ${erwartet}`],
  };
}

function vorbereiten(command: string, write: CoreWriteRequest,
                     zeile: string): CoreResult {
  return {
    kind: 'write_prepare',
    command,
    // Bewusst im Futur: hier ist noch nichts geschehen.
    lines: [`${zeile} — wird vorbereitet …`],
    write,
  };
}

function kontaktNeuErgebnis(argument: string): CoreResult {
  // Der Ablageort wird AUSDRUECKLICH genannt: auf diesem Mac gibt es
  // mehrere Container, und der Core waehlt keinen davon selbst aus.
  const [ziel, name] = teile(argument);
  if (!ziel || !name) {
    return fehlform('kontakt-neu',
                    'kontakt-neu <container> | <Vorname Nachname>');
  }
  return vorbereiten('kontakt-neu',
                     { phase: 'prepare', operation: 'kontakt_anlegen',
                       ziel, name },
                     'Kontakt anlegen');
}

function kontaktAendernErgebnis(argument: string): CoreResult {
  const [query, zuweisung] = teile(argument);
  const treffer = /^([^=]+)=(.*)$/.exec(zuweisung ?? '');
  if (!query || !treffer) {
    return fehlform('kontakt-aendern',
                    'kontakt-aendern <suchbegriff> | <feld> = <wert>');
  }
  const feld = treffer[1].trim().toLowerCase();
  const wert = treffer[2].trim();
  if (!wert) {
    return fehlform('kontakt-aendern', 'ein nicht leerer Wert nach dem =');
  }
  return vorbereiten('kontakt-aendern',
                     { phase: 'prepare', operation: 'kontakt_aendern',
                       query, feld, wert },
                     'Kontakt ändern');
}

function kontaktLoeschenErgebnis(argument: string): CoreResult {
  const query = argument.trim();
  if (!query) {
    return fehlform('kontakt-loeschen', 'kontakt-loeschen <suchbegriff>');
  }
  return vorbereiten('kontakt-loeschen',
                     { phase: 'prepare', operation: 'kontakt_loeschen', query },
                     'Kontakt löschen');
}

function terminNeuErgebnis(argument: string): CoreResult {
  // Ebenso der Zielkalender — neun sind hier beschreibbar.
  const [ziel, tag, vonBis, titel] = teile(argument);
  if (!ziel || !tag || !/^\d{2}:\d{2}-\d{2}:\d{2}$/.test(vonBis ?? '') || !titel) {
    return fehlform('termin-neu',
                    'termin-neu <kalender> | <tag> | <HH:MM-HH:MM> | <titel>');
  }
  return vorbereiten('termin-neu',
                     { phase: 'prepare', operation: 'termin_anlegen',
                       ziel, tag, vonBis, titel },
                     'Termin anlegen');
}

function terminAendernErgebnis(argument: string): CoreResult {
  const [tag, query, neuerTitel] = teile(argument);
  if (!tag || !query || !neuerTitel) {
    return fehlform('termin-aendern',
                    'termin-aendern <tag> | <suchbegriff> | <neuer titel>');
  }
  return vorbereiten('termin-aendern',
                     { phase: 'prepare', operation: 'termin_aendern',
                       tag, query, neuerTitel },
                     'Termin ändern');
}

/** Die EINZIGE Stelle, die eine Ausfuehrung anfordern kann. Sie verlangt
 *  die Kennung der konkreten vorbereiteten Mutation — eine Freigabe ohne
 *  Kennung gibt es nicht, und eine Kennung passt immer nur zu genau einer
 *  vorbereiteten Operation. */
function freigabeErgebnis(argument: string): CoreResult {
  const mutationId = argument.trim();
  if (!mutationId) {
    return fehlform('freigabe',
                    'freigabe <id> — die Kennung steht in der Vorschau');
  }
  return {
    kind: 'write_execute',
    command: 'freigabe',
    lines: ['Freigabe erteilt — wird ausgeführt …'],
    write: { phase: 'execute', mutationId },
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
    case 'kontakt-neu':
      return kontaktNeuErgebnis(argument);
    case 'kontakt-aendern':
      return kontaktAendernErgebnis(argument);
    case 'kontakt-loeschen':
      return kontaktLoeschenErgebnis(argument);
    case 'termin-neu':
      return terminNeuErgebnis(argument);
    case 'termin-aendern':
      return terminAendernErgebnis(argument);
    case 'freigabe':
      return freigabeErgebnis(argument);
    case 'abbrechen':
      return {
        kind: 'write_execute', command: 'abbrechen',
        lines: ['Vorbereitete Mutation verworfen.'],
        write: { phase: 'abort' },
      };
    default:
      // Die unbekannte Eingabe wird VOLLSTÄNDIG zurückgemeldet, nicht nur
      // ihr erstes Wort: wer „mach mal was" eingibt, muss genau das
      // wiederfinden. (Bestehendes Verhalten — die Zerlegung in Kommando
      // und Argument oben darf es nicht verkürzen.)
      return unbekanntErgebnis(roh.toLowerCase());
  }
}

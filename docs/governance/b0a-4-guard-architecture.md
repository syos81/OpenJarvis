---
Status: normativ (B0a-4 Architektur- und Variantenentscheidung)
Erzeugt aus: reale Eigentümer-, Modus-, ACL- und Schreibtests unter Benutzer `lukasklunder`, mechanische Auswertung der installierten Claude-Code-Fassung
Gültig ab: B0a-4
---

# Guard-Bootstrap — Variantenbewertung und Auswahl

Maßgeblich ist ausschließlich die tatsächliche Schutzgrenze. Keine Variante
wird wegen ihres Namens oder Speicherorts akzeptiert.

## §1 Bewertungsumgebung

| Größe | Wert |
|---|---|
| Benutzer der bewachten Sitzung | `lukasklunder`, uid 501, Gruppen u. a. `staff`, `admin` |
| macOS | 12.7.6 (21H1320), x86_64 |
| System Integrity Protection | aktiviert |
| Claude Code | 2.1.221, Entrypoint `claude-desktop` |
| `sudo -n true` in der Sitzung | scheitert: `sudo: a password is required` |

Die letzte Zeile ist die eigentliche Schutzgrenze dieses Rechners: die
bewachte Sitzung ist zwar in der Gruppe `admin`, kann aber ohne interaktive
Kennworteingabe **nicht** nach root eskalieren. Root-eigene Pfade sind für
eine automatisierte Sitzung damit unerreichbar. Das ist eine reale, geprüfte
Grenze — und keine kryptografische. Sie wird in §6 offen benannt.

## §2 Variante A — gemeinsames Git-Verzeichnis

Geprüft: `/Users/lukasklunder/Jarvis-Next/.git`
(`git rev-parse --git-common-dir`).

| Kriterium | Befund |
|---|---|
| Erreichbarkeit aus allen Worktrees | erfüllt |
| Eigentümer und Modus | `lukasklunder:staff`, `drwxr-xr-x` |
| Schreibbarkeit durch die Sitzung | **gegeben** |
| `git config --local` schreibbar | **gegeben**, mechanisch belegt |
| Schutz eines Unterpfads möglich | nur scheinbar: ein root-eigenes Unterverzeichnis ließe sich nicht ändern, aber `.git` selbst bleibt sitzungsschreibbar, also ist ein `mv` des geschützten Verzeichnisses und ein Ersatz durch ein eigenes möglich |
| Schutz der Hook-Registrierung | **nicht möglich**: Claude Code liest keine Hook-Registrierung aus dem Git-Verzeichnis |
| Umleitung über Repositorykonfiguration | möglich (`core.hooksPath`, Git-Aliase in sitzungsschreibbarer Konfiguration) |
| Neue, noch nicht integrierte Worktrees | erreichbar, aber ohne wirksame Registrierung wertlos |

**Ergebnis: verworfen.** Zwei unabhängige, mechanische Gründe: Die
Hook-Registrierung kann dort strukturell nicht liegen, und das Verzeichnis
ist samt jedem darin geschützten Unterpfad durch Umbenennen aushebelbar,
weil das Elternverzeichnis sitzungsschreibbar bleibt. Worktree-Übergreifen
allein ist kein Schutz.

## §3 Variante B — Claude-Konfiguration außerhalb des Repositorys

Die installierte Fassung 2.1.221 kennt mechanisch belegt fünf
Konfigurationsstufen: `policySettings` (Kennung `managed`), `userSettings`,
`projectSettings`, `localSettings`, `flagSettings`. Hook-Quellen werden
getrennt geführt; `policySettings` ist eine eigene Hook-Quelle neben
Projekt-, Lokal-, Plugin- und Sitzungshooks.

Der macOS-Pfad der Policy-Stufe ist im Binary fest verdrahtet:
`/Library/Application Support/ClaudeCode` mit `managed-settings.json` und
`managed-settings.d/`.

### §3.1 UnterVariante B1 — Benutzerkonfiguration

`~/.claude/settings.json` (`userSettings`). Liegt in einem normalen,
benutzerschreibbaren Home-Verzeichnis.

**Ergebnis: verworfen.** Die bewachte Sitzung kann die Datei anlegen,
ändern und löschen. Außerhalb des Repositorys zu liegen macht eine
Konfiguration nicht eigentümerkontrolliert.

### §3.2 UnterVariante B2 — Policy-/Managed-Konfiguration

| Kriterium | Befund |
|---|---|
| Elternverzeichnis `/Library/Application Support` | `root:admin`, `drwxr-xr-x` — Gruppe `admin` hat **kein** Schreibrecht |
| Anlegen von `ClaudeCode` durch die Sitzung | scheitert: `mkdir: Permission denied` |
| Von der installierten Fassung unterstützt | ja, mechanisch belegt |
| Durch Projekt- oder Lokalkonfiguration entfernbar | nein, eigene Hook-Quelle |
| Eskalation ohne Kennwort | nicht möglich (§1) |

**Ergebnis: gewählt für die Hook-Registrierung.**

## §4 Variante C — root-eigener Installationsbaum, gewählt

Für das Guard-Paket selbst wird ein eigener, root-eigener Baum verwendet.
Geprüfte Kandidaten:

| Pfad | Eigentümer und Modus | Sitzung schreibbar |
|---|---|---|
| `/usr/local` | `root:wheel`, `drwxr-xr-x` | nein (`mkdir` scheitert) |
| `/usr/local/lib` | `lukasklunder:admin`, `drwxrwxr-x` | **ja** (Homebrew-Eigentum) |
| `/Library/Application Support` | `root:admin`, `drwxr-xr-x` | nein |

`/usr/local/lib` ist damit ausdrücklich **ungeeignet**, obwohl es wie ein
Systempfad aussieht. Gewählt wird ein neues Verzeichnis direkt unterhalb von
`/usr/local`, das nur root anlegen und nur root umbenennen kann.

### §4.1 Gewählte Schutzkette

| Komponente | Ort | Eigentümer / Modus |
|---|---|---|
| Hook-Registrierung | `/Library/Application Support/ClaudeCode/managed-settings.json` | `root:wheel`, `0644` |
| Bootstrap-Wrapper | `/usr/local/jarvis-guard/bootstrap.sh` | `root:wheel`, `0755` |
| Bootstrap-Entrypoint | `/usr/local/jarvis-guard/bootstrap.py` | `root:wheel`, `0644` |
| Hash- und Versionsbindung | `/usr/local/jarvis-guard/active.json` | `root:wheel`, `0444` |
| Aktives Guard-Paket | `/usr/local/jarvis-guard/active/guard/` | `root:wheel`, Verz. `0755`, Dateien `0444` |
| Aktive Regelkonfiguration | `/usr/local/jarvis-guard/active/guard/rules.json` | `root:wheel`, `0444` |
| Interpreter | `/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9` | `root:wheel`, `0755`, gesamte Ahnenkette root |
| Ausnahmen (Prüfung) | `/usr/local/jarvis-guard/var/exceptions/pending/` | `root:wheel`, `0755` |
| Ausnahmen (Verbrauch) | `/usr/local/jarvis-guard/var/exceptions/spent/` | `root:wheel`, `01733` + ACL |
| Schutzprotokoll | `/usr/local/jarvis-guard/var/guard.log` | `root:wheel`, `0644` + ACL |
| Aktivierungsprotokoll | `/usr/local/jarvis-guard/var/activation.log` | `root:wheel`, `0600` |
| Rollback-Stand | `/usr/local/jarvis-guard/previous/` | `root:wheel` |

### §4.2 ACL-Nachweis

Zwei Eigenschaften brauchen mehr als Modusbits, weil der Wächter unter den
Rechten der bewachten Sitzung läuft. Beide wurden vorab real geprüft:

- `deny delete_child` auf einem Verzeichnis: die Sitzung kann eine
  Markerdatei anlegen, aber nicht entfernen (`unlink … Permission denied`).
  Damit ist der einmalige Ausnahmeverbrauch nicht rückgängig zu machen.
- `deny write,delete,writeattr,writeextattr,writesecurity,chown` plus
  `allow append,read,readattr` auf einer Datei: Anhängen gelingt,
  Überschreiben und Abschneiden scheitern. Damit ist das Protokoll
  append-only.

Wichtiger Nebenbefund aus demselben Test: Der **Eigentümer** einer Datei
kann eine ACL jederzeit entfernen. ACLs allein genügen deshalb nicht; sie
wirken nur, weil die Objekte root gehören und die Sitzung nicht root ist.

### §4.2a Interpreterbefund — `/usr/bin/python3` ist untauglich

Die naheliegende Wahl `/usr/bin/python3` ist auf diesem Rechner **unsicher**.
Die Datei selbst ist `root:wheel`, sie ist aber nur ein Stub. Real ausgeführt
wird:

```
/usr/bin/python3
  -> /Applications/Xcode.app/Contents/Developer/usr/bin/python3
  -> /Applications/Xcode.app/Contents/Developer/Library/Frameworks/
     Python3.framework/Versions/3.9/bin/python3.9
```

`/Applications/Xcode.app` gehört `lukasklunder:staff`, und ein Schreibversuch
der Sitzung in das Framework-Verzeichnis war erfolgreich. Ein Interpreter,
den die bewachte Sitzung austauschen kann, hebt die gesamte Schutzkette auf.

Gewählt wird deshalb der Interpreter der Command Line Tools. Für ihn gilt
`root:wheel` für die Datei **und** für jedes Elternverzeichnis bis `/`; ein
Schreibversuch der Sitzung scheitert.

Daraus folgt eine allgemeine Prüfregel im Bootstrap: nicht nur die Datei,
sondern die **gesamte Ahnenkette** von Interpreter und Installationswurzel
muss root gehören und darf für Gruppe und andere nicht schreibbar sein.
Dieselbe Regel entwertet auch `/usr/local/lib` aus §4 automatisch. Zusätzlich
wird nicht nur der deklarierte, sondern auch der tatsächlich laufende
Interpreter geprüft.

### §4.3 Wiederherstellungsweg für Lukas

```
sudo /bin/rm -rf /usr/local/jarvis-guard
sudo /bin/rm -f "/Library/Application Support/ClaudeCode/managed-settings.json"
```

Danach ist nur noch der repositoryseitige, ausdrücklich nicht
vertrauenswürdige Hook aktiv. Ein Rollback auf die vorherige aktive Fassung
liegt unter `/usr/local/jarvis-guard/previous/`.

## §5 Warum dieselbe Sitzung den Wächter nicht abschalten kann

1. Jede Komponente der Kette gehört root; die Sitzung ist uid 501.
2. Jedes Elternverzeichnis der Kette gehört root und ist für andere nicht
   schreibbar, also ist auch Umbenennen ausgeschlossen.
3. Die Hook-Registrierung liegt in der Policy-Stufe; Projekt- und
   Lokalkonfiguration können sie nicht entfernen.
4. Der Bootstrap leitet seinen Ort aus seinem eigenen absoluten Pfad ab und
   liest weder `CLAUDE_PROJECT_DIR` noch `PATH`, `PYTHONPATH` noch das
   Arbeitsverzeichnis.
5. Der Bootstrap prüft vor jedem Lauf Eigentümer, Modus, Symlinkfreiheit,
   Version und Paket-Hash und blockiert bei jeder Abweichung.
6. Der Interpreter ist absolut und root-eigen; ein benutzerschreibbarer
   Wrapper wird nicht verwendet.
7. `sudo` ohne Kennwort scheitert.

## §6 Offene Restbefunde — ausdrücklich benannt

1. **Die Claude-Code-Anwendung selbst ist benutzerschreibbar.** Sie liegt
   unter `~/Library/Application Support/Claude/claude-code/2.1.221/` und
   gehört `lukasklunder`. Wer die Anwendung ersetzt, umgeht jede
   Konfiguration, die diese Anwendung liest — auch die Policy-Stufe. Das ist
   keine Eigenschaft dieser Guard-Architektur, sondern die Vertrauenswurzel
   jeder Hook-basierten Absicherung. Kein Bestandteil dieses Blocks kann
   das schließen.
2. **Die Sitzung läuft unter einem Administrator-Konto.** Mit dem Kennwort
   des Eigentümers ist jede Grenze aus §4 aufhebbar. Die Grenze lautet
   „erfordert eine interaktive Eigentümerauthentisierung", nicht
   „technisch unmöglich".
3. **Das Schutzprotokoll ist fälschungsoffen nach vorn.** Einträge können
   weder entfernt noch überschrieben werden, aber die Sitzung kann eigene
   Einträge anhängen. Eine Signatur würde nichts ändern, weil jeder
   Schlüssel, den der Wächter lesen kann, auch der Sitzung zugänglich ist.

Diese drei Punkte sind Befunde, keine Mängel der Umsetzung. Sie werden im
B0b-Handoff wiederholt.

## §7 Deklarierte Sollmerkmalszahl

B0a-4 deklariert **35** eigene Pflichtmerkmale (`B0A4-001` bis `B0A4-035`).
Die dreißig Merkmale des Auftrags sind vollständig enthalten; fünf weitere
sind ergänzt. Diese Zahl wird nicht mehr verringert und kein deklariertes
Merkmal wird zusammengefasst.

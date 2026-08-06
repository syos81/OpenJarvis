---
Status: normativ (Errata zu B0a-3, erstellt in B0a-4)
Art: Nachtrag — die ursprüngliche Fassung bleibt über `a093687` unverändert nachvollziehbar
Erzeugt aus: Git-Reflog, Git-Objektdaten, Quelltextstand des Hooks zum Zeitpunkt von B0a-3
---

# Errata B0a-3 — lokale Entstehungsgeschichte und Wächterlage

Dies ist ein **Addendum**. Es korrigiert keine Evidenz rückwirkend, ändert
keine Datei eines abgeschlossenen Commits und berührt `a093687` nicht. Der
B0a-3-Abschlussbericht bleibt als historisches Dokument gültig; er war an den
hier genannten Stellen unvollständig.

## §1 Lokale Entstehungskette des Integrations-Commits

Der Reflog der Kalenderlinie belegt mechanisch folgende Kette:

| Schritt | Objekt | Reflog-Eintrag |
|---|---|---|
| 1 | `d2bce8f` | `commit (merge)` |
| 2 | `b872f91` | `commit (amend)` |
| 3 | `ad84559` | `commit (amend)` |
| 4 | `a093687` | `commit (amend)` |

Es gab damit **drei lokale `commit --amend`-Vorgänge** zwischen dem
ursprünglichen Merge-Objekt `d2bce8f` und dem veröffentlichten Stand
`a093687`.

## §2 Was veröffentlicht wurde

Die drei Zwischenstände `d2bce8f`, `b872f91` und `ad84559` wurden **nicht**
auf `origin` veröffentlicht. Gepusht wurde die Kalenderlinie von `8e6e206`
direkt auf `a093687`. Der finale Remote-Stand von
`origin/spike/calendar-foundation-intel-2026-08-04` ist `a093687`.

## §3 Finaler Graph gegen lokale Entstehungsgeschichte

Der finale Git-Graph enthält genau **einen Merge-Commit**: `a093687` mit den
beiden Eltern `8e6e206` (Kalender) und `4e47144` (Tooling), in dieser
Reihenfolge. Diese Aussage des B0a-3-Berichts ist zutreffend.

Sie beschreibt jedoch ausschließlich die **Graphform**. Die **lokale
Entstehungsgeschichte** dieses Objekts — drei Amends — ist im Graphen nicht
sichtbar und wurde im Bericht nicht genannt. Beides sind unterschiedliche
Größen: die Graphform ist eine Eigenschaft des veröffentlichten Objekts, die
Entstehungsgeschichte eine Eigenschaft des lokalen Arbeitsverlaufs. Der
B0a-3-Bericht hat nur die erste genannt und damit einen unvollständigen
Eindruck erzeugt.

## §4 Warum die Amends nicht verhindert wurden

Der zum Zeitpunkt von B0a-3 aktive PreToolUse-Wächter enthielt keine Regel
gegen `git commit --amend`. Die harte Sperrliste umfasste `git push`,
`git reset --hard`, `git rebase`, `git clean`, `git stash drop`, `rm -rf`
und den Zugriff auf `.env`-Dateien — Amend war nicht darunter. Die drei
Vorgänge waren daher regelkonform im Sinne der damals implementierten
Regelmenge und wurden nicht blockiert.

## §5 Fail-open-Verhalten des damaligen Hooks

Der damalige Hook `.claude/hooks/pretooluse_guard.sh` beendete sich mit
Exit 0 — also ohne jede Entscheidung — wenn:

1. `CLAUDE_PROJECT_DIR` leer war und auch `git rev-parse --show-toplevel`
   nichts lieferte,
2. das Verzeichnis `tools/gates` im aktuellen Worktree fehlte,
3. kein geeigneter Python-Interpreter gefunden wurde.

Der Dateikopf beschrieb dieses Verhalten ausdrücklich als Entwurfsziel
(„der Hook darf die Sitzung nie unterbrechen"). Das ist ein
**fail-open**-Entwurf und mit einer fail-closed-Architektur unvereinbar.

## §6 Fehlender durchgehender Wirksamkeitsnachweis

Der Kalender-Worktree enthielt vor der Integration von `4e47144` kein
`tools/gates`. Nach Befund §5.2 beendete sich der Hook in genau diesem Fall
ohne Entscheidung. Für den Teil von B0a-3 **vor** der Integration existiert
deshalb kein Nachweis einer aktiven Schutzwirkung des Wächters im
Kalender-Worktree; es existiert im Gegenteil ein struktureller Beleg dafür,
dass er dort nicht wirksam sein konnte.

Für den Zeitraum **nach** der Integration ist die Wirksamkeit belegbar: eine
Anforderung eines rekursiven `rm` im Kalender-Worktree wurde am 2026-08-06
mit `deny.rm_rf` blockiert und im gitignorierten Hook-Rohlog
(`.gate-runtime/hook-logs/`) vermerkt.

## §7 Was dieser Nachtrag nicht tut

- Er ändert `a093687` nicht und amendiert ihn nicht.
- Er verändert keine Datei eines abgeschlossenen Commits.
- Er entfernt und verändert keine historische Evidenz; die B0a-3-Evidenz
  bleibt unter ihren ursprünglichen Hashes gebunden
  (`config/gates/history/b0a-3-integration.acceptance.json`).
- Er erklärt keine der drei Zwischenfassungen nachträglich für ungültig oder
  für nie existent.

## §8 Folgen für B0a-4

Aus den Befunden §4 bis §6 folgen die Pflichtmerkmale von B0a-4:
argumentbasierte harte Sperre von `git commit --amend`, vollständige
Beseitigung der fail-open-Pfade, ein worktree-unabhängiger und
eigentümerkontrollierter Wächter sowie ein Live-Nachweis in einem Worktree
ohne integriertes Tooling.

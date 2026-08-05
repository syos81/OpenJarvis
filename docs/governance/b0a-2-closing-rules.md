---
Status: normativ (B0a-2 Governance); Abschluss-, Commit- und Push-Regeln
---

# B0a-2 — Abschluss, Commit und Push

## §1 Zwei getrennte B0a-Commits

Der ursprüngliche Ein-Commit-Schnitt für B0a ist durch den bewusst
beschlossenen Schnitt ersetzt. Es gilt:

* genau **ein** Commit für B0a-1:
  `chore(tooling): bootstrap deterministic gates and evidence`
* genau **ein weiterer** Commit für B0a-2:
  `chore(governance): consolidate B0a architecture guards`
* insgesamt zwei klar getrennte B0a-Commits.

Der B0a-1-Commit wird **nicht** amendiert. Es entstehen keine zusätzlichen
B0a-Commits, kein Merge, kein Rebase, kein Cherry-pick, kein Tag und kein
Release.

## §2 Push ist ausschließlich Eigentümerhandlung

> Jeder Arbeitsblock endet für Claude und andere Agenten nach dem
> erfolgreichen lokalen Commit. Pushes sind ausschließlich Eigentümerhandlungen
> außerhalb des Blocks. Ein Agent darf keinen Push ausführen, dafür keinen
> `ask`- oder Freigabepfad aufrufen und die Push-Sperre weder verändern noch
> über einen alternativen Prozess, Client, Hook, Alias, Unterprozess oder
> sonstigen Umweg umgehen. Als Pushanweisung darf ausschließlich ein einzelner,
> exakter manueller Befehl für den aktuellen Zielbranch ausgegeben werden. Das
> Ausbleiben des Eigentümer-Pushes macht einen ansonsten vollständig
> bestandenen lokalen Block nicht zu `fail` oder `blocked`.

Mechanisch abgesichert ist das durch:

* die harte Deny-Regel `Bash(git push:*)` in `.claude/settings.json`,
* dieselbe harte Regel im `PreToolUse`-Guard (`tools/gates/hookguard.py`), die
  niemals zu `ask` herabgestuft wird,
* das Fehlen jedes Agenten-Ausnahmepfads für den Push.

Der Pushstatus eines lokal abgeschlossenen Blocks lautet:

```text
not_performed_owner_action
```

Der einzige zulässige manuelle Eigentümerbefehl für den aktuellen Zielbranch:

```bash
git push --set-upstream origin tooling/gates-v1
```

Kein zweiter oder alternativer Push-Befehl, kein Force-Push, kein Push auf einen
Produktbranch und kein Merge in den Kalender-Branch.

## §3 Abschlussgates

```bash
scripts/gate.sh --block b0a-2-governance --phase preflight
scripts/gate.sh --block b0a-2-governance --phase targeted
scripts/gate.sh --block b0a-2-governance --phase offline-final
scripts/gate.sh --block b0a-2-governance --phase platform-live
scripts/gate.sh --block b0a-2-governance --phase module-final
```

Das Readiness-Manifest läuft ausschließlich prüfend:

```bash
scripts/gate.sh --block tooling-merge-readiness --phase preflight
scripts/gate.sh --block tooling-merge-readiness --phase offline-final
```

Für B0a-2 ergibt `platform-live` begründet `not_applicable`. `module-final`
prüft zusätzlich die vollständigen B0a-1-Werkzeuge erneut als unverändert
funktionsfähig.

---
DEC-ID: DEC-068
Titel: Eigentümergrenzen: abschließende Klassen der Eigentümerhandlungen
Status: accepted
Regel-Alias: Eigentümergrenzen
Registerpfad: refs/governance/dec-reservations
Block: B0g
---

# DEC-068 — Eigentümergrenzen: abschließende Klassen der Eigentümerhandlungen

## Kontext

Das Guard-Vertrauensmodell definiert seit B0b die Eigentümerauthentifizierungsgrenze; die Push-Sperre bestand nur als CLAUDE.md-Prosa; die Commit-Pläne führten driftende Verbotslisten. B0g führt die belegten Klassen in einer Entscheidung zusammen.

## Entscheidung (normativ)

Folgende Handlungsklassen sind ausschließlich Eigentümerhandlungen; ein Agent führt sie nie aus, ruft keinen Freigabepfad dafür auf, umgeht die Sperren nicht über alternative Prozesse, Clients, Hooks, Aliasse oder Unterprozesse und gibt höchstens einen einzelnen exakten manuellen Befehl aus: (1) jeder Branch-Push; (2) jeder Push auf refs/governance/dec-reservations; (3) die Freigabe (release) einer reservierten DEC-ID sowie Reservierung und Vergabe als Ref-Fortschreibung; (4) Guard-Aktivierung und jede sudo-geschützte Installation; (5) physische Mutation der rootgehaltenen Installationsziele des Guards (Install-Target /usr/local/jarvis-guard und geschützte Policy-Pfade); (6) die weiteren in Commit-Plänen deklarierten Eigentümeroperationen (kein Force-Push, kein --force-with-lease, kein Push auf Produktbranches, kein Merge/Rebase/Cherry-pick/Tag/Release/Amend durch Agenten, keine Sammlung von Ausnahmeobjekten). Das Ausbleiben einer Eigentümerhandlung macht einen ansonsten bestandenen lokalen Block nicht zu fail oder blocked; der Zustand heißt not_performed_owner_action. Die Vertrauensgrenze bleibt ehrlich: requires_interactive_owner_authentication, nicht technically_impossible.

## Geltungsbereich

Alle Agentenläufe in diesem Repository; alle Remote-Mutationen; die Guard-Installationskette.

## Ausdrücklich nicht geregelt

Die fachliche Entscheidung des Eigentümers selbst; Handlungen außerhalb der belegten Klassen (keine neue Sicherheitsbehauptung).

## Mechanische Durchsetzung

Guard-Regeln (git_push/git_update_ref hart verboten, Verstoßkorpus mit Governance-Ref-Fixtures), .claude/settings.json-Denies, PreToolUse-Kette, claim-lint gegen stärkere Schutzbehauptungen (tg-/of-claim-lint), push_status-Prüfung der Commit-Pläne, decreg druckt Eigentümerbefehle und führt nichts aus.

## Herkunft

config/governance/guard-trust-model.json (57dafef, B0b; gehärtet B0d) für die Authentifizierungsgrenze; CLAUDE.md-Abschnitt Commit und Push (vor-Block-Ära) für die Push-Klassen; forbidden_operations der Commit-Pläne B0a-4 bis B0g; owner_action-Kennzeichnungen in tools/decreg und tools/guardops. Dieses Dokument vereinheitlicht die driftenden Listen, ohne eine Klasse zu erfinden.

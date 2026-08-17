# Kontakte — zwei latente Befunde, festgehalten statt repariert

**Stand:** 2026-08-17, Intel MacBook Air (x86_64, macOS 12.7.6)
**Zweig:** `feature/everyday-readiness-v1-2026-08-16`

Beide Befunde sind beim Bau des Kontingentzählers und des Löschgates
aufgefallen. Beide sind ausdrücklich **nicht** repariert worden — sie stehen
hier, damit sie nicht ein drittes Mal von jemandem neu entdeckt werden.

## B-1 · `PATCH /{contact_id}` schluckt jedes Pfadsegment

**Was.** Die Kontaktroute `PATCH /v1/personal/contacts/{contact_id}` bindet
jedes Segment an ihren Pfadparameter. `PATCH …/write-quota`,
`PATCH …/capabilities` und `PATCH …/categories` landen deshalb nicht bei einem
`405 Method Not Allowed`, sondern in der Vorbereitung einer Kontaktänderung
und scheitern dort mit `422` an der Nutzlast.

**Gemessen.** Alle drei Leserouten verhalten sich gleich: `POST`, `PUT` und
`DELETE` ergeben `405`, `PATCH` ergibt `422`.

**Warum es heute nichts aufreisst.** Der Aufruf erreicht einen Weg, der die
betroffene Ressource gar nicht kennt: Die Kontingentzeile wird dabei nicht
berührt, und ein Vorgang entsteht nicht, weil die Nutzlastprüfung vorher
greift. Der Befund ist eine Unsauberkeit der Routenform, keine offene Tür.

**Was daraus nicht folgen darf.** Kein Test darf für diese Pfade ein `405`
behaupten — das gäbe es nicht, und die Zusicherung wäre falsch.
`tests/personal/contacts/test_write_quota.py::test_die_route_ist_nur_lesend`
sagt den gemessenen Zustand und prüft stattdessen das, worauf es ankommt:
Keiner dieser Wege bewegt den Stand.

**Nicht heute.** Eine Reparatur hiesse, die Kontaktroute auf eine engere
Pfadform festzulegen (etwa eine Kennungsgestalt im Routenmuster). Das berührt
jede Leseroute des Moduls und gehört in einen eigenen Block.

## B-2 · Kein Gate-Block deckt das Kontaktmodul ab

**Was.** `config/gates/blocks/` kennt vierzehn Blöcke — Kalender, Governance,
Tooling. Keiner davon nimmt `src/personaljarvis/contacts/**` oder
`frontend/src/personal/contacts/**` in seinen Umfang. `scripts/gate.sh` hat
für dieses Modul also nichts zu prüfen.

**Folge.** Die Prüfung des Kontaktzweigs sind heute die Suiten
(`tests/personal/contacts`, `frontend … src/personal/contacts`, `tsc`,
`ruff`). Das ist der Stand, in dem auch die vorangegangenen Blöcke dieses
Zweigs abgeschlossen wurden.

**Was daraus nicht folgen darf.** Ein Gatelauf gegen einen Kalenderblock ist
kein Beleg für das Kontaktmodul. Ein Bericht, der ein `pass` eines fremden
Blocks als Kontaktbeleg führt, wäre eine stärkere Behauptung als die Messung.

**Nicht heute.** Ein eigener Block braucht Umfang, Phasenzuschnitt und eine
Merkmalslinie; das ist eine Governance-Handlung und keine Nebenarbeit.

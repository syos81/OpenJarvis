---
Status: normativ
Architektur-Baseline: v3
Freigabedatum: 2026-07-31
Baseline-Tag: openjarvis-baseline-2026-07-27
Maßgebliche AV-Regeln: AV-4, AV-11, AV-16, AV-33
Zugehörige ADRs: ADR-0003, ADR-0019, ADR-0021, ADR-0022
Verwandte DEC-Einträge: DEC-011, DEC-039, DEC-048; offen: DEC-D13 (Home-Server-Secret-Store)
---

# ADR-0023: Hausverwaltungs-Systemgrenzen, Immoware24 und Workspace-Sicherheitskontexte

- **ADR-Status:** accepted
- **Datum:** 2026-07-31

## Kontext

Hausverwaltung (HV) ist ein zentraler zukünftiger Arbeitsbereich von Personal Jarvis und wird **nicht** lediglich als Kontaktkategorie behandelt. Zugleich darf Jarvis nicht unbemerkt eine konkurrierende vollständige Hausverwaltungsdatenbank aufbauen. Der Begriff „Space" wird umgangssprachlich verwendet; die kanonische Entität bleibt der **Workspace** (Glossar, 06 §6) — dieser ADR schärft Workspaces als Sicherheits- und Datenschutzgrenzen.

## Entscheidung

1. **HV-Zielbild (verbindlich):** eigener HV-Arbeitskontext · Objekt- und Vorgangszuordnung · Eingangsverarbeitung · Dokumentenprüfung und Ablage · Fristen und Wiedervorlagen · Schadens- und Anliegenbearbeitung · Handwerkerkoordination · Objekt-Onboarding · Eigentümer-, Mieter- und Handwerkerkommunikation · Berichte, Checklisten, Verträge und Protokolle · Immoware24-Zugriff · Nextcloud-Zugriff · Mailanalyse · kontrollierte Internet- und Rechtsrecherche · später mögliche Buchhaltungs- und Abrechnungsunterstützung.
2. **Systemgrenzen (verbindlich):** Immoware24 bzw. das jeweils eingesetzte HV-Fachsystem bleibt grundsätzlich **fachliche Quelle** für dort verwaltete Stammdaten, Verträge, Buchungen und Abrechnungen. Nextcloud bleibt die Dokumentenablage, soweit später nichts anderes entschieden wird. Mailprovider bleiben Quelle der Kommunikation. **Jarvis verbindet, projiziert, plant und führt kontrollierte Prozesse aus**; lokale Arbeits-, Verknüpfungs-, Audit- und Automationsdaten sind zulässig, wenn ihre Rolle im Speicher-Register (06 §2) eindeutig dokumentiert ist. Jarvis erzeugt **keine** unbemerkte konkurrierende HV-Volldatenbank; Fachdaten des Fachsystems erscheinen lokal nur als kontrollierte Projektion oder klar deklarierter Arbeitsbestand.
3. **Immoware24-Integrationsprüfung (verbindliche Reihenfolge, ADR-0022 Punkt 4):** (1) offizielle API oder Partnerschnittstelle → (2) dokumentierte Export-, Import- oder Integrationsmöglichkeiten → (3) kontrollierte Browserautomation → (4) visuelle Bildschirmsteuerung nur als Rückfall. **Die Existenz einer öffentlichen Immoware24-API ist nicht verifiziert und wird nicht behauptet (UNGEKLÄRT);** die Prüfung erfolgt beim Einstieg in das erste HV-Modul.
4. **HV als mehrere vertikale Module:** HV wird nicht als ein unbegrenztes Modul geplant. Mögliche spätere vertikale Module (Reihenfolge bewusst offen, je 100-Prozent-Regel aus ADR-0019): HV-Eingangsverarbeitung · HV-Dokumentenablage · HV-Vorgangs- und Fristenmanagement · Immoware24-Arbeitsabläufe · Handwerkerkoordination · Objekt-Onboarding. Keine dieser Funktionen wird jetzt implementiert; eine Position vor Modul 4 existiert nicht (DEC-045).
5. **Workspaces als Daten- und Sicherheitskontexte:** Privat, Arbeit, HV und Trading werden als getrennte Kontexte geführt (konfigurierbar, DEC-039). Verbindliche Eigenschaften: getrennte Credentials (CredentialReferences je Konto/Workspace, 09 §4) · getrennte Datenquellen (Collection-Zuordnung, 08 §1) · getrennte Suchbereiche · getrennte Agentenmemory-Bereiche (stets abgeleitet, nie kanonisch, AV-16) · getrennte Cloudfreigaben (Egress-Regeln je Workspace, 12 §3) · sichtbarer aktiver Kontext in der UI · Schutz vor versehentlicher Vermischung · kontrollierte kontextübergreifende Suche nur als bewusste, geloggte Operation · Empfänger- und Egressprüfung vor jedem Versand · Datenminimierung · Retention · Export und Löschung je Kontext · Provenienz und letzter Synchronisationszeitpunkt sichtbar. **Mieter und Vermieter sind Rollen innerhalb eines fachlichen Kontexts (06 §6); HV ist dagegen eine Sicherheits-, Datenschutz- und Organisationsgrenze.**

## Geprüfte Alternativen

- **HV nur als Rollen-/Tag-Modell im Kontakte-Modul** — verworfen: bildet Vorgänge, Fristen, Objekte und Systemgrenzen nicht ab.
- **Eigene vollständige HV-Datenbank als kanonische Wahrheit** — verworfen: konkurrierende Wahrheit gegen das Fachsystem; nur klar deklarierte Arbeits-/Projektionsbestände sind zulässig.
- **Sofortige Immoware24-Anbindung per Browserautomation** — verworfen: Prioritätenfolge verlangt zuerst API-/Exportprüfung; kein Modulbedarf jetzt.

## Konsequenzen

Kein HV-Code in diesem Auftrag. Beim Einstieg in das erste HV-Modul: Integrationsprüfung nach Punkt 3, Speicher-Register-Einträge nach Punkt 2, Workspace-Härtung nach Punkt 5. DEC-D13 bleibt offen.

## Verweise

Primärdokumente: 06 §2/§6, 08 §1, 09 §4, 12 §3. Entscheidungen: DEC-048.

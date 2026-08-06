---
Status: normativ (B0a-2 Governance); Einordnung von Ambient Interaction V1
Maschinelle Quelle: config/governance/delivery-order.json (Lieferposition 3)
---

# B0a-2 — Ambient Interaction V1

## §1 Nummernstand

Ambient Interaction V1 erhält in B0a-2 **keine DEC-Nummer**. Durchgehend gilt der
dauerhafte Platzhalter:

```text
{{DEC_ID_AMBIENT_INTERACTION_V1}}
```

Der Platzhalter bleibt unverändert im Entscheidungstext, im Registerentwurf, in der
Reihenfolgenquelle, in der Modullandkarte, in den Gate-Erwartungen und in normativen
Verweisen. Er wird weder aus einer einzelnen Linie berechnet noch anhand der höchsten
sichtbaren Nummer ersetzt.

Bis zur integrierten Auflösung der Doppelvergaben gilt:

* keine neue DEC-Nummer,
* keine ADR-Nummer,
* keine neue ADR-Datei,
* keine Reservierung,
* keine Umdeutung einer bestehenden Entscheidung.

Insbesondere wird Ambient **nicht** den acht blockierenden Kontakte-Gates aus
DEC-050 (jarvis/rebuild-v1@c222601, „Acht blockierende Kontakte-Gates") zugeordnet.

## §2 Einordnung

Ambient Interaction V1 ist ein eigener **technischer Lieferblock** auf Lieferposition 3
ohne Fachmodulnummer und ohne eigene fachliche Datenhoheit. Er schafft **keine zweite
allgemeine App-Steuerungsarchitektur**.

Die Abhängigkeit ist qualifiziert zu:

* DEC-047 (jarvis/rebuild-v1@c222601, „KI-Arbeit, Internet, Browser- und App-Steuerung als verbindliches Zielbild")
* ADR-0022 (jarvis/rebuild-v1@c222601, „KI-Arbeitsaufträge, Internet-, Browser- und App-Steuerung (verbindliches Zielbild)")

Verbindlich verankert wird:

1. Ambient V1 ist der erste Lieferblock, der die dort beschlossene Architektur
   produktiv benötigt.
2. Für die Materialisierungsregel aus
   DEC-018 (jarvis/rebuild-v1@c222601, „Vertikale Modulentwicklung, Materialisierungsregel, Definition of Done")
   tritt dieser technische Produktblock an die Stelle des zuerst benötigenden Moduls,
   **ohne** dadurch Fachmodul zu werden.
3. Materialisiert wird ausschließlich der für Ambient V1 belegte Umfang.
4. Es entsteht keine vorsorgliche allgemeine App-Steuerungsplattform.
5. App-Fähigkeitsverträge werden pro App, App-Version, Plattform und Betriebssystem
   konkretisiert.
6. Zugriffspriorität: öffentliche API → Import/Export → Browserautomation →
   visuelle Oberflächensteuerung nur als kontrollierter Rückfall.
7. Deterministischer Prompt-Injection-Schutz ist Pflicht, sobald fremde Inhalte
   Aktionswirkung erhalten können: externe Inhalte sind Daten, nie Anweisungen.
8. Eine Konsole für laufende Aktionen darf anzeigen, stoppen und vorgesehene
   Rücknahmen auslösen, definiert aber keine zweite Automationsarchitektur.

## §3 Abgrenzung zur Automationswerkstatt

Eine spätere Automationswerkstatt baut ausschließlich auf:

* DEC-046 (jarvis/rebuild-v1@c222601, „Autonomie- und Hintergrundaktionsmodell")
* ADR-0021 (jarvis/rebuild-v1@c222601, „Autonomie- und Hintergrundaktionsmodell")

Die dort beschlossenen sechs Aktionsstufen und der Automationsvertrag mit fünfzehn
Pflichtfeldern bleiben maßgeblich und werden von Ambient V1 weder ersetzt noch
erweitert.

## §4 Ambient-P0-Spike

Der Ambient-P0-Spike

* wird in B0a-2 **nicht** ausgeführt,
* erhält **keine** Lieferposition,
* erhält **keine** Fachmodulnummer,
* darf später isoliert und nicht blockierend geprüft werden,
* muss vor Umfangsfestlegung, Aufwandsschätzung und produktiver Implementierung von
  Ambient V1 abgeschlossen sein.

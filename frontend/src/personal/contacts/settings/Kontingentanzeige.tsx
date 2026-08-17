// Der sichtbare Stand des Kontingents einer Dauerfreigabe.
//
// Das Kontingent lag seit dem 2026-08-17 im Kern und setzte dort auch die
// Grenze durch — nur sah der Eigentümer es nicht. Eine Grenze, die man erst
// beim Anschlagen bemerkt, ist keine Auskunft, sondern eine Überraschung.
//
// Drei Eigenschaften, die dieser Baustein ausdrücklich hat:
//
//   * **Er formuliert nichts selbst.** Der Satz kommt wörtlich aus dem Kern
//     (`QuotaState.als_text`), aus derselben Stelle, an der `execute`
//     scheitert. Ein hier nachgebauter Satz wäre ein zweiter Vertrag.
//   * **Er ändert nichts.** Ein einziger lesender Abruf, kein Verbrauch, kein
//     Rücksetzweg — den gibt es nirgends, und das ist Absicht.
//   * **Er schweigt ohne Dauerfreigabe.** Dann gibt es keine Aktivierung und
//     nichts zu zählen; die Grenze eines Vorgangs ist dann die Zeit, und eine
//     Zahl an dieser Stelle wäre schlicht falsch.

import { useEffect, useState } from 'react';

import { getWriteQuota, type WriteQuota } from '../api';

export function Kontingentanzeige({ schluessel }: {
  /**
   * Ändert sich dieser Wert, wird neu gelesen.
   *
   * Bewusst kein Zeitgeber: Der Stand ändert sich nur durch eine Handlung des
   * Eigentümers, und der Aufrufer weiß, wann er eine ausgelöst hat. Ein
   * Intervall fragte fortwährend nach einer Zahl, die sich fast nie ändert.
   */
  schluessel?: unknown;
}) {
  const [stand, setStand] = useState<WriteQuota | null>(null);

  useEffect(() => {
    let lebt = true;
    getWriteQuota()
      .then((q) => { if (lebt) setStand(q); })
      // Ein fehlgeschlagener Abruf zeigt **nichts** an. Eine geratene Zahl
      // wäre hier schlimmer als gar keine: Der Eigentümer plant danach.
      .catch(() => { if (lebt) setStand(null); });
    return () => { lebt = false; };
  }, [schluessel]);

  if (stand === null || !stand.active) return null;

  return (
    <p
      data-testid="contacts-kontingent"
      style={{
        margin: '8px 0 0', font: 'var(--pjc-font-label)',
        color: stand.exhausted
          ? 'var(--color-warning)' : 'var(--color-text-secondary)',
      }}
    >
      {stand.text}
    </p>
  );
}

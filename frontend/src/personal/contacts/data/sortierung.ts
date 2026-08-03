// Sortier- und Abschnittslogik der Kontaktliste.
//
// Apple Kontakte ordnet nach Nachname. Die Zusammenfassung trägt keinen
// getrennten Nachnamen, deshalb wird er aus dem Anzeigenamen abgeleitet:
// alles ab dem zweiten Wort zählt als Nachname. Das ist eine bewusste,
// deterministische Näherung; die M2-Abnahme prüft sie gegen das
// Referenzverhalten.

import type { ContactSummary } from '../api';

export function sortSchluessel(k: ContactSummary): string {
  const teile = k.display_name.trim().split(/\s+/);
  return teile.length > 1
    ? `${teile.slice(1).join(' ')} ${teile[0]}`
    : k.display_name;
}

export function sortiereKontakte(liste: ContactSummary[]): ContactSummary[] {
  return [...liste].sort(
    (a, z) => sortSchluessel(a).localeCompare(sortSchluessel(z), 'de'),
  );
}

export function abschnittsBuchstabe(k: ContactSummary): string {
  const erst = sortSchluessel(k).trim().charAt(0).toUpperCase();
  if (!/[A-ZÄÖÜ]/.test(erst)) return '#';
  return erst.replace('Ä', 'A').replace('Ö', 'O').replace('Ü', 'U');
}

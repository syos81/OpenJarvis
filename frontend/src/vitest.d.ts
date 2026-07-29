// Typen der jest-dom-Matcher für `tsc --noEmit`.
//
// Ohne diese Referenz kennt TypeScript `toBeInTheDocument`, `toBeDisabled`
// und Verwandte nicht — die Tests liefen dann grün, während die Typprüfung
// rot wäre. Beides muss dieselbe Wahrheit sehen.

/// <reference types="@testing-library/jest-dom" />

export {};

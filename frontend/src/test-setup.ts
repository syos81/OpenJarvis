// Vitest-Setup.
//
// Bewusst defensiv: das Repo hat Tests in beiden Umgebungen. Die älteren
// laufen unter `node` und stellen sich ihre Stubs selbst; die
// Interaktionstests der Kontakte-Seite laufen unter `jsdom` (Docblock
// `@vitest-environment jsdom` in der jeweiligen Datei).
//
// Deshalb wird hier nichts erzwungen, was ohne DOM scheitern würde — es
// entsteht keine zweite Testwelt und kein zweiter Runner.

import { afterEach, expect } from 'vitest';

const hatDom = typeof document !== 'undefined';

if (hatDom) {
  const matchers = await import('@testing-library/jest-dom/matchers');
  expect.extend(matchers.default ?? matchers);

  const { cleanup } = await import('@testing-library/react');
  afterEach(() => {
    cleanup();
  });

  // jsdom kennt `matchMedia` nicht; einzelne shadcn-Bausteine fragen danach.
  if (!window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
}

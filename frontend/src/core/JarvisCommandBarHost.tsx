// Jarvis Core v0 — Einhängepunkt der Command Bar.
//
// Der Host besitzt genau zwei Dinge: das Öffnen per Cmd/Ctrl+K und den
// Kontext, den die App ohnehin schon kennt (die aktive Route). Er liegt
// neben der Bar statt in `App.tsx`, damit das Öffnen und Schliessen ohne
// die Netzwerk- und Startlogik der App prüfbar ist.

import { useCallback, useEffect, useState } from 'react';
import { useLocation } from 'react-router';
import { JarvisCommandBar } from './JarvisCommandBar';

export function JarvisCommandBarHost() {
  const [offen, setOffen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    const aufTaste = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
      if (e.key.toLowerCase() !== 'k') return;
      e.preventDefault();
      setOffen((vorher) => !vorher);
    };
    window.addEventListener('keydown', aufTaste);
    return () => window.removeEventListener('keydown', aufTaste);
  }, []);

  const schliessen = useCallback(() => setOffen(false), []);

  if (!offen) return null;
  return <JarvisCommandBar context={{ route: pathname }} onClose={schliessen} />;
}

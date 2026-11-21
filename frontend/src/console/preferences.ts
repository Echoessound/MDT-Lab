import { useState } from 'react';

export function usePreference(key: string, fallback: () => boolean, on: string, off: string) {
  const [value, setValue] = useState(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored === on || stored === off) return stored === on;
    } catch { /* Restricted browser storage still allows in-session preferences. */ }
    return fallback();
  });
  const toggle = () => {
    const next = !value;
    setValue(next);
    try { localStorage.setItem(key, next ? on : off); } catch { /* Keep the in-session choice. */ }
  };
  return [value, toggle] as const;
}

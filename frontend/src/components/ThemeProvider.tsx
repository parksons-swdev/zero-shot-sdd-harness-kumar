'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'

/**
 * ChatGPT-style dark/light theme (Phase 3).
 *
 * The FIRST-PAINT theme is applied by the inline no-flash script in
 * `layout.tsx` (reads localStorage, falls back to `prefers-color-scheme`) so
 * the `.dark` class is already on <html> before React hydrates. This provider
 * simply syncs React state with what the DOM already shows and exposes a
 * toggle that flips the class, persists the choice to localStorage, and
 * re-renders theme-aware consumers (e.g. the Plotly charts).
 */

export type Theme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'csv-insight-theme'

interface ThemeContextValue {
  theme: Theme
  toggle: () => void
  setTheme: (theme: Theme) => void
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: 'light',
  toggle: () => {},
  setTheme: () => {},
})

function domTheme(): Theme {
  if (typeof document !== 'undefined' && document.documentElement.classList.contains('dark')) {
    return 'dark'
  }
  return 'light'
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Start 'light' to match the server-rendered markup, then reconcile with the
  // class the no-flash script already applied, on mount (avoids hydration
  // mismatch while still honoring the persisted / system preference).
  const [theme, setThemeState] = useState<Theme>('light')

  useEffect(() => {
    setThemeState(domTheme())
  }, [])

  const setTheme = useCallback((next: Theme) => {
    const root = document.documentElement
    if (next === 'dark') root.classList.add('dark')
    else root.classList.remove('dark')
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next)
    } catch {
      // localStorage unavailable — theme still applies for this session.
    }
    setThemeState(next)
  }, [])

  const toggle = useCallback(() => {
    setTheme(domTheme() === 'dark' ? 'light' : 'dark')
  }, [setTheme])

  return (
    <ThemeContext.Provider value={{ theme, toggle, setTheme }}>{children}</ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}

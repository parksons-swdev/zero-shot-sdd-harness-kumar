'use client'

import { useCallback, useEffect, useState } from 'react'
import Sidebar from '@/components/Sidebar'

/**
 * ChatGPT-style app shell (Phase 3): a collapsible left sidebar beside a
 * full-height main region that hosts every page. The collapse preference is
 * persisted in localStorage. This wraps all routes via the root layout, so
 * the sidebar/theme persist across client navigations.
 */

const COLLAPSE_STORAGE_KEY = 'csv-insight-sidebar-collapsed'

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_STORAGE_KEY) === '1')
    } catch {
      // ignore
    }
  }, [])

  const toggle = useCallback(() => {
    setCollapsed(prev => {
      const next = !prev
      try {
        localStorage.setItem(COLLAPSE_STORAGE_KEY, next ? '1' : '0')
      } catch {
        // ignore
      }
      return next
    })
  }, [])

  return (
    <div className="flex h-screen overflow-hidden bg-white text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <main className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {children}
      </main>
    </div>
  )
}

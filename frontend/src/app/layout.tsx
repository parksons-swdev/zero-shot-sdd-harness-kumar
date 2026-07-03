import type { Metadata } from 'next'
import './globals.css'
import { ThemeProvider } from '@/components/ThemeProvider'
import AppShell from '@/components/AppShell'

export const metadata: Metadata = {
  title: 'CSV Insight Agent',
  description: 'Ask questions about your CSV data and get real, explained answers',
}

// Runs synchronously before first paint so the correct theme class is on <html>
// with no flash of the wrong theme. Precedence: explicit localStorage choice,
// else the OS `prefers-color-scheme`. Must mirror THEME_STORAGE_KEY.
const NO_FLASH_THEME_SCRIPT = `(function(){try{var k='csv-insight-theme';var s=localStorage.getItem(k);var dark=s?s==='dark':window.matchMedia('(prefers-color-scheme: dark)').matches;var c=document.documentElement.classList;if(dark)c.add('dark');else c.remove('dark');}catch(e){}})();`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH_THEME_SCRIPT }} />
      </head>
      <body className="antialiased">
        <ThemeProvider>
          <AppShell>{children}</AppShell>
        </ThemeProvider>
      </body>
    </html>
  )
}

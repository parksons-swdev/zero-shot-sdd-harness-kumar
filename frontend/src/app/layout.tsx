import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'
import NavStub from '@/components/NavStub'

export const metadata: Metadata = {
  title: 'CSV Insight Agent',
  description: 'Ask questions about your CSV data and get real, explained answers',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-50 text-gray-900 antialiased">
        <nav className="border-b border-gray-200 bg-white">
          <div className="mx-auto flex max-w-4xl items-center gap-6 px-4 py-3">
            <span className="text-sm font-semibold tracking-tight text-gray-900">CSV Insight Agent</span>
            <div className="flex items-center gap-4 text-sm">
              <Link href="/" className="text-gray-600 hover:text-gray-900">
                Analyze
              </Link>
              <Link href="/history" className="text-gray-600 hover:text-gray-900">
                History
              </Link>
              <NavStub />
            </div>
          </div>
        </nav>
        {children}
      </body>
    </html>
  )
}

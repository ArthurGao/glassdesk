import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { useT } from '@/lib/i18n'

const NAV = [
  { to: '/', label: 'chat' },
  { to: '/knowledge', label: 'knowledge' },
  { to: '/insights', label: 'insights' },
] as const

export function AppShell({
  brandName,
  brandColor,
  username,
  onLogout,
  children,
}: {
  brandName: string
  brandColor?: string
  username?: string
  onLogout?: () => void
  children: ReactNode
}) {
  const t = useT()
  return (
    <div className="flex h-screen flex-col bg-slate-50 text-slate-900">
      <header
        className="flex items-center gap-6 border-b border-t-4 border-slate-200 bg-white px-4 py-2"
        style={brandColor ? { borderTopColor: brandColor } : undefined}
      >
        <span className="font-semibold">{brandName}</span>
        <nav className="flex gap-4 text-sm">
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="text-slate-600 hover:text-slate-900"
              activeProps={{ className: 'font-medium text-slate-900' }}
              activeOptions={{ exact: true }}
            >
              {t.nav[item.label]}
            </Link>
          ))}
        </nav>
        {username && (
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span>{username}</span>
            <button type="button" onClick={onLogout} className="text-slate-500 hover:text-slate-900">
              {t.nav.logout}
            </button>
          </div>
        )}
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  )
}

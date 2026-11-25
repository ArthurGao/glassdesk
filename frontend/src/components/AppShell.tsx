import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

const NAV = [
  { to: '/', label: '聊天' },
  { to: '/knowledge', label: '知识库' },
  { to: '/insights', label: '洞察' },
] as const

export function AppShell({
  brandName,
  username,
  onLogout,
  children,
}: {
  brandName: string
  username?: string
  onLogout?: () => void
  children: ReactNode
}) {
  return (
    <div className="flex h-screen flex-col bg-slate-50 text-slate-900">
      <header className="flex items-center gap-6 border-b border-slate-200 bg-white px-4 py-2">
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
              {item.label}
            </Link>
          ))}
        </nav>
        {username && (
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span>{username}</span>
            <button type="button" onClick={onLogout} className="text-slate-500 hover:text-slate-900">
              退出
            </button>
          </div>
        )}
      </header>
      <main className="min-h-0 flex-1">{children}</main>
    </div>
  )
}

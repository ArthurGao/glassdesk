import { useQueryClient } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { login } from '@/client/sdk.gen'
import { meQuery } from '@/lib/session'

export const Route = createFileRoute('/login')({ component: LoginPage })

function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const { data, response } = await login({ body: { username, password } })
      if (!data) {
        setError(response?.status === 401 ? '用户名或密码错误' : '登录失败，请稍后再试')
        setPassword('')
        return
      }
      queryClient.setQueryData(meQuery.queryKey, data)
      await navigate({ to: '/' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-screen items-center justify-center bg-slate-50">
      <form onSubmit={onSubmit} className="w-80 space-y-4 rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="text-lg font-semibold">登录</h1>
        <label className="block text-sm">
          用户名
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
          />
        </label>
        <label className="block text-sm">
          密码
          <input
            type="password"
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded bg-slate-900 py-1.5 text-sm text-white disabled:opacity-50"
        >
          登录
        </button>
      </form>
    </div>
  )
}

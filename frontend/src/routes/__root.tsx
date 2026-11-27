import type { QueryClient } from '@tanstack/react-query'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import {
  createRootRouteWithContext,
  Outlet,
  redirect,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router'
import { logout } from '@/client/sdk.gen'
import { AppShell } from '@/components/AppShell'
import { brandingQuery } from '@/lib/branding'
import { HTML_LANG, MESSAGES, MessagesContext } from '@/lib/i18n'
import { meQuery } from '@/lib/session'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  beforeLoad: async ({ context, location }) => {
    // branding (the locale) alongside the session check: the page waits for it before rendering
    const branding = context.queryClient.prefetchQuery(brandingQuery)
    if (location.pathname === '/login') return
    const [user] = await Promise.all([context.queryClient.ensureQueryData(meQuery), branding])
    if (!user) throw redirect({ to: '/login' })
  },
  component: Root,
})

function Root() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const { data: user } = useQuery(meQuery)
  const { data: brand, isError: noBrand } = useQuery(brandingQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const locale = brand?.locale ?? 'zh'
  // the browser tab carries the customer's name too (login page included)
  useEffect(() => {
    if (brand) document.title = brand.name
  }, [brand])
  useEffect(() => {
    document.documentElement.lang = HTML_LANG[locale]
  }, [locale])
  // nothing until the locale is known, so an en deployment never flashes Chinese
  if (!brand && !noBrand) return null

  async function onLogout() {
    await logout()
    queryClient.setQueryData(meQuery.queryKey, null)
    await navigate({ to: '/login' })
  }

  return (
    <MessagesContext.Provider value={MESSAGES[locale]}>
      {pathname === '/login' ? (
        <Outlet />
      ) : (
        <AppShell
          brandName={brand?.name ?? ''}
          brandColor={brand?.color}
          username={user?.username}
          onLogout={onLogout}
        >
          <Outlet />
        </AppShell>
      )}
    </MessagesContext.Provider>
  )
}

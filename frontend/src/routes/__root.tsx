import type { QueryClient } from '@tanstack/react-query'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
import { meQuery } from '@/lib/session'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  beforeLoad: async ({ context, location }) => {
    if (location.pathname === '/login') return
    const user = await context.queryClient.ensureQueryData(meQuery)
    if (!user) throw redirect({ to: '/login' })
  },
  component: Root,
})

function Root() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const { data: user } = useQuery(meQuery)
  const { data: brand } = useQuery(brandingQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  if (pathname === '/login') return <Outlet />

  async function onLogout() {
    await logout()
    queryClient.setQueryData(meQuery.queryKey, null)
    await navigate({ to: '/login' })
  }

  return (
    <AppShell
      brandName={brand?.name ?? ''}
      brandColor={brand?.color}
      username={user?.username}
      onLogout={onLogout}
    >
      <Outlet />
    </AppShell>
  )
}

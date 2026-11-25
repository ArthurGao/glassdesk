import { queryOptions } from '@tanstack/react-query'
import { me } from '@/client/sdk.gen'
import type { MeOut } from '@/client/types.gen'

/** The logged-in user, or null when the session cookie is missing or no longer valid. */
export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: async (): Promise<MeOut | null> => {
    const { data, response } = await me()
    if (response?.status === 401) return null
    if (!data) throw new Error(`/api/me answered ${response?.status ?? 'no response'}`)
    return data
  },
  staleTime: Infinity,
})

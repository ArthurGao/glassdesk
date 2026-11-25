import { queryOptions } from '@tanstack/react-query'
import { branding } from '@/client/sdk.gen'

/** The customer's name, colour, welcome and example questions (deployment settings). */
export const brandingQuery = queryOptions({
  queryKey: ['branding'],
  queryFn: async () => (await branding({ throwOnError: true })).data,
  staleTime: Infinity,
})

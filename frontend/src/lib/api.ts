import { client } from '@/client/client.gen'

/** The API is same-origin (the backend serves the SPA; Vite proxies /api in dev). */
export function configureApi() {
  client.setConfig({ baseUrl: window.location.origin, credentials: 'same-origin' })
}

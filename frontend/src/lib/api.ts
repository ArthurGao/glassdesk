import { client } from '@/client/client.gen'

/** The API is same-origin (the backend serves the SPA; Vite proxies /api in dev). */
export function configureApi() {
  client.setConfig({ baseUrl: window.location.origin, credentials: 'same-origin' })
}

/** A decision request that is done: it succeeded, or someone already decided (409) or the item
 * is gone (404). Either way the page drops the item instead of showing an error. */
export function isSettled(response: Response | undefined): boolean {
  return !!response && (response.ok || response.status === 404 || response.status === 409)
}

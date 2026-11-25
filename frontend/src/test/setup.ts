import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { configureApi } from '@/lib/api'
import { MockEventSource } from './eventSource'
import { server } from './server'

beforeAll(() => {
  configureApi()
  server.listen({ onUnhandledFrame: 'error' })
})
afterEach(() => {
  cleanup()
  MockEventSource.instances = []
  server.resetHandlers()
})
afterAll(() => server.close())

window.scrollTo = () => {}
Element.prototype.scrollIntoView ??= () => {}

globalThis.EventSource = MockEventSource as unknown as typeof EventSource

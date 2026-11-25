import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { configureApi } from '@/lib/api'
import { server } from './server'

beforeAll(() => {
  configureApi()
  server.listen({ onUnhandledFrame: 'error' })
})
afterEach(() => {
  cleanup()
  server.resetHandlers()
})
afterAll(() => server.close())

window.scrollTo = () => {}
Element.prototype.scrollIntoView ??= () => {}

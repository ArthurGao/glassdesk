import { setupServer } from 'msw/node'

// Each test file adds its handlers with server.use(); unhandled requests fail the test.
export const server = setupServer()

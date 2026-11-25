import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

export const BRANDING = {
  name: 'Acme 知识台',
  color: '#0f766e',
  welcome: '问我公司制度、流程和常见问题。',
  examples: ['出差住宿上限是多少？', '年假怎么请？'],
}

// The branding every page reads is served by default; each test file adds its own handlers with
// server.use(), and unhandled requests fail the test.
export const server = setupServer(http.get('*/api/branding', () => HttpResponse.json(BRANDING)))

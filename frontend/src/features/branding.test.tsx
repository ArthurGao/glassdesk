import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

function loggedIn() {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ username: 'alice', role: 'member' })),
    http.get('*/api/conversations', () => HttpResponse.json([])),
    http.get('*/api/suggestions', () => HttpResponse.json([])),
  )
}

test('the shell shows the customer name from the branding', async () => {
  loggedIn()
  renderApp('/')
  expect(await screen.findByText('Acme 知识台')).toBeInTheDocument()
  expect(screen.queryByText('glassdesk')).toBeNull()
  expect(document.title).toBe('Acme 知识台')
})

test('the login page carries the customer name', async () => {
  server.use(http.get('*/api/me', () => HttpResponse.json({ detail: 'x' }, { status: 401 })))
  renderApp('/login')
  expect(await screen.findByRole('heading', { name: '登录 Acme 知识台' })).toBeInTheDocument()
})

test('an empty chat welcomes and offers the example questions', async () => {
  loggedIn()
  server.use(
    http.post('*/api/conversations', () =>
      HttpResponse.json(
        { id: 'c9', title: '新会话', created_at: '2026-11-25T00:00:00Z', updated_at: '2026-11-25T00:00:00Z' },
        { status: 201 },
      ),
    ),
    http.get('*/api/conversations/c9/answers', () => HttpResponse.json([])),
  )
  const { router } = renderApp('/')
  expect(await screen.findByText('问我公司制度、流程和常见问题。')).toBeInTheDocument()
  await userEvent.setup().click(screen.getByRole('button', { name: '出差住宿上限是多少？' }))
  await waitFor(() => expect(router.state.location.search).toEqual({ c: 'c9' }))
  expect(await screen.findByLabelText('问题')).toHaveValue('出差住宿上限是多少？')
})

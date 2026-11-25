import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { server } from '@/test/server'
import { renderApp } from '@/test/render'

test('shows 用户名或密码错误 on 401 and keeps the username', async () => {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ detail: 'not logged in' }, { status: 401 })),
    http.post('*/api/auth/login', () =>
      HttpResponse.json({ detail: '用户名或密码错误' }, { status: 401 }),
    ),
  )
  renderApp('/login')
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('用户名'), 'alice')
  await user.type(screen.getByLabelText('密码'), 'wrong')
  await user.click(screen.getByRole('button', { name: '登录' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('用户名或密码错误')
  expect(screen.getByLabelText('用户名')).toHaveValue('alice')
})

test('navigates to / after 200', async () => {
  let loggedIn = false
  server.use(
    http.get('*/api/me', () =>
      loggedIn
        ? HttpResponse.json({ username: 'alice', role: 'member' })
        : HttpResponse.json({ detail: 'not logged in' }, { status: 401 }),
    ),
    http.post('*/api/auth/login', () => {
      loggedIn = true
      return HttpResponse.json({ username: 'alice', role: 'member' })
    }),
  )
  const { router } = renderApp('/login')
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('用户名'), 'alice')
  await user.type(screen.getByLabelText('密码'), 'right')
  await user.click(screen.getByRole('button', { name: '登录' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  expect(await screen.findByText('alice')).toBeInTheDocument()
})

test('an anonymous visit to / redirects to /login', async () => {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ detail: 'not logged in' }, { status: 401 })),
  )
  const { router } = renderApp('/')
  await waitFor(() => expect(router.state.location.pathname).toBe('/login'))
})

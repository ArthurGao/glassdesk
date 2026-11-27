import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { renderApp } from '@/test/render'
import { BRANDING, server } from '@/test/server'

function english() {
  server.use(http.get('*/api/branding', () => HttpResponse.json({ ...BRANDING, locale: 'en' })))
}

function loggedIn() {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ username: 'alice', role: 'member' })),
    http.get('*/api/conversations', () => HttpResponse.json([])),
    http.get('*/api/suggestions', () => HttpResponse.json([])),
  )
}

test('an en deployment signs in in English', async () => {
  english()
  server.use(http.get('*/api/me', () => HttpResponse.json({ detail: 'x' }, { status: 401 })))
  renderApp('/login')
  expect(await screen.findByRole('heading', { name: 'Sign in to Acme 知识台' })).toBeInTheDocument()
  expect(screen.getByLabelText('Username')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  expect(document.documentElement.lang).toBe('en')
})

test('an en deployment shows the shell and chat in English, with no Chinese copy', async () => {
  english()
  loggedIn()
  renderApp('/')
  expect(await screen.findByRole('link', { name: 'Knowledge' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '+ New conversation' })).toBeInTheDocument()
  expect(screen.getByText("Ask a question and the assistant's every step shows here.")).toBeInTheDocument()
  expect(screen.queryByText('聊天')).toBeNull()
  expect(screen.queryByText('执行过程')).toBeNull()
})

test('a zh deployment keeps the Chinese page', async () => {
  loggedIn()
  renderApp('/')
  expect(await screen.findByRole('link', { name: '知识库' })).toBeInTheDocument()
  expect(screen.getByText('执行过程')).toBeInTheDocument()
  expect(document.documentElement.lang).toBe('zh-CN') // as index.html ships it
})

import { render, screen } from '@testing-library/react'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { AppShell } from './AppShell'

function renderShell() {
  const rootRoute = createRootRoute({
    component: () => (
      <AppShell brandName="Acme">
        <p>content</p>
      </AppShell>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

test('renders brand and three nav links in order', async () => {
  renderShell()
  expect(await screen.findByText('Acme')).toBeInTheDocument()
  const nav = screen.getByRole('navigation')
  const links = Array.from(nav.querySelectorAll('a'))
  expect(links.map((a) => a.textContent)).toEqual(['聊天', '知识库', '洞察'])
  expect(links.map((a) => a.getAttribute('href'))).toEqual(['/', '/knowledge', '/insights'])
})

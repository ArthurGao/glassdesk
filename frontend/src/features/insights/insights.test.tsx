import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { InsightsOut } from '@/client/types.gen'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

function day(d: string, over: Partial<InsightsOut['totals']> = {}): InsightsOut['totals'] {
  return { day: d, answers: 0, failed: 0, tokens: 0, tokens_unknown_runs: 0, cost_usd: null, cost_unknown_runs: 0, ...over }
}

const BODY: InsightsOut = {
  days: [day('2026-11-24', { answers: 3, failed: 1, tokens: 240, cost_usd: 0.03, cost_unknown_runs: 1 }), day('2026-11-25')],
  totals: day('2026-11-25', { answers: 3, failed: 1, tokens: 240, cost_usd: 0.03, cost_unknown_runs: 1 }),
  helpful_rate: null,
  rated: 0,
  kb: { entries_by_status: { active: 4, verified: 1 }, pending_reviews: 2, awaiting_user: 1, gaps: [{ query: '海外差旅住宿标准', count: 3 }] },
  demo: true,
}

function api(role: 'member' | 'reviewer', body: InsightsOut | null = BODY) {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ username: 'rita', role })),
    http.get('*/api/insights', () =>
      body ? HttpResponse.json(body) : HttpResponse.json({ detail: '需要审核权限' }, { status: 403 }),
    ),
  )
}

test('tiles keep unknown cost apart and show an empty rate as —', async () => {
  api('reviewer')
  renderApp('/insights')
  const tiles = await screen.findByRole('list', { name: '概览' })
  expect(within(tiles).getByText('回答').nextSibling).toHaveTextContent('3')
  expect(within(tiles).getByText('成本').nextSibling).toHaveTextContent('$0.0300（1 次未知）')
  expect(within(tiles).getByText('好评率').nextSibling).toHaveTextContent('—')
  expect(screen.getByText('演示数据')).toBeInTheDocument()
})

test('a day with no cost reported shows 未知 rather than 0', async () => {
  api('reviewer', { ...BODY, days: [day('2026-11-25', { answers: 2, cost_unknown_runs: 2 })] })
  renderApp('/insights')
  const row = (await screen.findByText('2026-11-25')).closest('tr')!
  expect(row).toHaveTextContent('未知')
  expect(row).not.toHaveTextContent('$0')
})

test('gaps and KB counts come from steward, or say 未配置', async () => {
  api('reviewer')
  renderApp('/insights')
  expect(await screen.findByText('海外差旅住宿标准')).toBeInTheDocument()
  expect(screen.getByText('待审核 2')).toBeInTheDocument()
})

test('without steward stats the KB block says 未配置', async () => {
  api('reviewer', { ...BODY, kb: null, demo: false })
  renderApp('/insights')
  expect(await screen.findByText('知识库统计未配置')).toBeInTheDocument()
  expect(screen.queryByText('演示数据')).toBeNull()
})

test('a member is told insights need the reviewer role', async () => {
  api('member', null)
  renderApp('/insights')
  expect(await screen.findByText('需要审核权限才能查看洞察。')).toBeInTheDocument()
})

test('tokens say how many runs reported none', async () => {
  api('reviewer', { ...BODY, totals: day('2026-11-25', { answers: 2, tokens: 120, tokens_unknown_runs: 1 }) })
  renderApp('/insights')
  const tiles = await screen.findByRole('list', { name: '概览' })
  expect(within(tiles).getByText('tokens').nextSibling).toHaveTextContent('120（1 次未知）')
})

test('an error says so instead of a blank page', async () => {
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ username: 'rita', role: 'reviewer' })),
    http.get('*/api/insights', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
  )
  renderApp('/insights')
  expect(await screen.findByRole('alert')).toHaveTextContent('洞察暂时无法加载')
})

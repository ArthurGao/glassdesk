import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import type { CandidateOut, EntryOut } from '@/client/types.gen'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

const NOW = '2026-11-25T09:00:00Z'
const ENTRY: EntryOut = {
  id: 'e1', title: '报销时限', content: '30 天内提交', status: 'active', risk_level: 'low',
  origin: 'manual', hit_count: null, updated_at: NOW,
}
const REVIEW: CandidateOut = {
  id: 'r1', stage: 'awaiting_review', risk_level: 'high', title: '价格表', content: 'A 套餐 99 元',
  reason: '命中高风险关键词', origin: 'api', created_at: NOW,
}

function api(role: 'member' | 'reviewer', reviews: CandidateOut[] = []) {
  const queue = [...reviews]
  server.use(
    http.get('*/api/me', () => HttpResponse.json({ username: 'alice', role })),
    http.get('*/api/kb/entries', () => HttpResponse.json([ENTRY])),
    http.get('*/api/kb/documents', () => HttpResponse.json([])),
    http.get('*/api/kb/reviews', () => HttpResponse.json(queue)),
  )
  return queue
}

test('entries show status in words and an unknown hit count as —', async () => {
  api('member')
  renderApp('/knowledge')
  const row = (await screen.findByText('报销时限')).closest('tr')!
  expect(row).toHaveTextContent('生效')
  expect(row).toHaveTextContent('—')
})

test('a member sees no 待审核 tab', async () => {
  api('member')
  renderApp('/knowledge')
  await screen.findByRole('tab', { name: '条目' })
  expect(screen.getByRole('tab', { name: '文档' })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: '待审核' })).toBeNull()
})

test('a new entry that needs review says it was sent for review', async () => {
  api('member')
  server.use(
    http.post('*/api/kb/entries', () =>
      HttpResponse.json({ entry: null, candidate: REVIEW }, { status: 201 }),
    ),
  )
  renderApp('/knowledge')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '新建条目' }))
  await user.type(screen.getByLabelText('标题'), '价格表')
  await user.type(screen.getByLabelText('内容'), 'A 套餐 99 元')
  await user.click(screen.getByRole('button', { name: '保存' }))
  expect(await screen.findByRole('status')).toHaveTextContent('已提交审核')
})

test('a reviewer approves and the row leaves the queue', async () => {
  const queue = api('reviewer', [REVIEW])
  let note: unknown = null
  server.use(
    http.post('*/api/kb/reviews/r1/approve', async ({ request }) => {
      note = await request.json()
      queue.splice(0)
      return HttpResponse.json({ status: 'accepted', entry_status: 'verified' })
    }),
  )
  renderApp('/knowledge')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: '待审核' }))
  const row = (await screen.findByText('价格表')).closest('tr')!
  expect(row).toHaveTextContent('命中高风险关键词')
  await user.click(within(row).getByRole('button', { name: '批准' }))
  await waitFor(() => expect(screen.queryByText('价格表')).toBeNull())
  expect(note).toEqual({ note: null })
})

test('保存 is held while steward judges the entry, so a second click writes nothing', async () => {
  api('member')
  let posts = 0
  server.use(
    http.post('*/api/kb/entries', async () => {
      posts += 1
      await delay(200) // steward runs a model before it answers (about 30 s on qwen3:8b)
      return HttpResponse.json({ entry: ENTRY, candidate: null }, { status: 201 })
    }),
  )
  renderApp('/knowledge')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '新建条目' }))
  await user.type(screen.getByLabelText('标题'), '报销时限')
  await user.type(screen.getByLabelText('内容'), '30 天内提交')
  await user.click(screen.getByRole('button', { name: '保存' }))
  const saving = screen.getByRole('button', { name: '保存中…' })
  expect(saving).toBeDisabled()
  await user.click(saving)
  expect(await screen.findByRole('status')).toHaveTextContent('已存入知识库')
  expect(posts).toBe(1)
})

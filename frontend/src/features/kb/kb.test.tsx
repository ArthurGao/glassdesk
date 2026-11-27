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

test('上传 is held while the document is being sent', async () => {
  api('member')
  let posts = 0
  server.use(
    http.post('*/api/kb/documents', async () => {
      posts += 1
      await delay(200)
      return HttpResponse.json({ document: null, candidate: null }, { status: 201 })
    }),
  )
  renderApp('/knowledge')
  const user = userEvent.setup()
  await user.click(await screen.findByRole('tab', { name: '文档' }))
  await user.upload(await screen.findByLabelText('文件'), new File(['30 天'], 'a.md', { type: 'text/markdown' }))
  await user.click(screen.getByRole('button', { name: '上传' }))
  const sending = screen.getByRole('button', { name: '上传中…' })
  expect(sending).toBeDisabled()
  await user.click(sending)
  expect(await screen.findByRole('status')).toHaveTextContent('已上传')
  expect(posts).toBe(1)
})

const OLD: EntryOut = { ...ENTRY, id: 'e2', title: '旧制度', status: 'deprecated' }

function entriesApi(role: 'member' | 'reviewer') {
  const entries = [ENTRY, OLD]
  const posted: unknown[] = []
  api(role)
  server.use(
    http.get('*/api/kb/entries', () => HttpResponse.json(entries)),
    http.post('*/api/kb/entries/e1/deprecate', async ({ request }) => {
      posted.push(await request.json())
      entries[0] = { ...ENTRY, status: 'deprecated' }
      return HttpResponse.json(entries[0])
    }),
  )
  return posted
}

test('a member gets no 停用 button', async () => {
  entriesApi('member')
  renderApp('/knowledge')
  await screen.findByText('报销时限')
  expect(screen.queryByRole('button', { name: '停用' })).toBeNull()
})

test('a reviewer deprecates an entry after confirming in the dialog', async () => {
  const posted = entriesApi('reviewer')
  renderApp('/knowledge')
  const user = userEvent.setup()
  const row = (await screen.findByText('报销时限')).closest('tr')!
  // only rows still in use can be deprecated
  expect(within(screen.getByText('旧制度').closest('tr')!).queryByRole('button')).toBeNull()
  await user.click(within(row).getByRole('button', { name: '停用' }))
  let dialog = screen.getByRole('dialog', { name: '停用这个条目？' })
  expect(dialog).toHaveTextContent('报销时限')
  await user.click(within(dialog).getByRole('button', { name: '取消' }))
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(posted).toEqual([])

  await user.click(within(row).getByRole('button', { name: '停用' }))
  dialog = screen.getByRole('dialog', { name: '停用这个条目？' })
  await user.type(within(dialog).getByLabelText('原因（可选）'), '已被新制度取代')
  await user.click(within(dialog).getByRole('button', { name: '停用' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(posted).toEqual([{ reason: '已被新制度取代' }])
  // refetched: the row now reads 已停用 and offers nothing more
  const updated = (await screen.findByText('报销时限')).closest('tr')!
  await waitFor(() => expect(updated).toHaveTextContent('已停用'))
  expect(within(updated).queryByRole('button')).toBeNull()
})

test('Escape closes the deprecate dialog without deprecating', async () => {
  const posted = entriesApi('reviewer')
  renderApp('/knowledge')
  const user = userEvent.setup()
  const row = (await screen.findByText('报销时限')).closest('tr')!
  await user.click(within(row).getByRole('button', { name: '停用' }))
  await user.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).toBeNull()
  expect(posted).toEqual([])
})

test('a failed deprecation keeps the dialog open and says so', async () => {
  entriesApi('reviewer')
  server.use(
    http.post('*/api/kb/entries/e1/deprecate', () =>
      HttpResponse.json({ detail: '知识库暂时不可用' }, { status: 503 }),
    ),
  )
  renderApp('/knowledge')
  const user = userEvent.setup()
  const row = (await screen.findByText('报销时限')).closest('tr')!
  await user.click(within(row).getByRole('button', { name: '停用' }))
  const dialog = screen.getByRole('dialog', { name: '停用这个条目？' })
  await user.click(within(dialog).getByRole('button', { name: '停用' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('操作失败，请稍后再试')
})

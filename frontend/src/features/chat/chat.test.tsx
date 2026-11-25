import { act, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { Answer, CardOut, Step } from '@/client/types.gen'
import { MockEventSource } from '@/test/eventSource'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

const CONV = { id: 'c1', title: '报销', created_at: '2026-11-25T09:00:00Z', updated_at: '2026-11-25T09:00:00Z' }

function step(over: Partial<Step>): Step {
  return {
    seq: 1, run_id: 'r1', kind: 'question', title: '问题', detail: null, status: 'ok',
    started_at: '2026-11-25T09:00:00Z', duration_ms: null, usage: null, ...over,
  }
}

const ANSWER: Answer = {
  run_id: 'r1',
  question: '报销上限是多少？',
  text: '上限 800 元[1]，需审批[3]。',
  failed: false,
  citations: [
    { n: 1, item_id: 'e1', kind: 'entry', title: '差旅制度 v3', source: 'kb', text: '住宿上限每晚 800 元', verified: true },
  ],
  unmatched: [3],
}

function api({ answers = [] as Answer[], askStatus = 202, cards = [] as CardOut[] } = {}) {
  const stored = [...answers]
  server.use(
    http.get('*/api/suggestions', () => HttpResponse.json(cards)),
    http.get('*/api/me', () => HttpResponse.json({ username: 'alice', role: 'member' })),
    http.get('*/api/conversations', () => HttpResponse.json([CONV])),
    http.get('*/api/conversations/c1/answers', () => HttpResponse.json(stored)),
    http.post('*/api/conversations/c1/messages', () =>
      askStatus === 202
        ? HttpResponse.json({ run_id: 'r2' }, { status: 202 })
        : HttpResponse.json({ detail: '上一个问题还在处理中' }, { status: askStatus }),
    ),
  )
  return stored
}

/** Opening a conversation attaches to its stream once; nothing is running, so it ends. */
async function openIdle() {
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  act(() => MockEventSource.last().emit('end', {}))
}

async function ask(text: string) {
  const user = userEvent.setup()
  await user.type(await screen.findByLabelText('问题'), text)
  await user.click(screen.getByRole('button', { name: '发送' }))
}

test('Send is disabled while a stream is open and re-enabled after the answer', async () => {
  const stored = api()
  renderApp('/?c=c1')
  await openIdle()
  await ask('报销上限是多少？')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(2))
  const stream = MockEventSource.last()
  expect(stream.url).toContain('/api/conversations/c1/stream')
  // typed text is not enough while the run goes: the stream holds Send
  await userEvent.setup().type(screen.getByLabelText('问题'), '下一个问题')
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  stored.push({ ...ANSWER, run_id: 'r2' }) // what the backend now lists
  act(() => {
    stream.emit('step', step({ seq: 3, run_id: 'r2' }), '3')
    stream.emit('answer', { ...ANSWER, run_id: 'r2' })
    stream.emit('end', {})
  })
  await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeEnabled())
  expect(stream.closed).toBe(true)
  expect(screen.getByText(/上限 800 元/)).toBeInTheDocument()
})

test('409 shows 上一个问题还在处理中', async () => {
  api({ askStatus: 409 })
  renderApp('/?c=c1')
  await openIdle()
  await ask('再问一次')
  expect(await screen.findByRole('alert')).toHaveTextContent('上一个问题还在处理中')
})

test('citation [1] opens a popover with the passage; unmatched [3] is not a button', async () => {
  api({ answers: [ANSWER] })
  renderApp('/?c=c1')
  await openIdle()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '[1]' }))
  const popover = await screen.findByRole('dialog')
  expect(popover).toHaveTextContent('差旅制度 v3')
  expect(popover).toHaveTextContent('住宿上限每晚 800 元')
  expect(popover).toHaveTextContent('已验证')
  expect(screen.queryByRole('button', { name: '[3]' })).toBeNull()
  expect(screen.getByText(/需审批\[3\]/)).toBeInTheDocument()
})

test('timeline shows 未知 when cost_usd is null', async () => {
  api()
  renderApp('/?c=c1')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  act(() => {
    const s = MockEventSource.last()
    s.emit('step', step({ seq: 8, kind: 'finished', title: '完成', duration_ms: 2620,
      usage: { input: 400, output: 50, cost_usd: null } }), '8')
    s.emit('end', {})
  })
  const timeline = screen.getByRole('complementary', { name: '执行过程' })
  expect(await within(timeline).findByText('成本 未知')).toBeInTheDocument()
  expect(within(timeline).getByText('450 tokens')).toBeInTheDocument()
})

test('an error step renders as an error and the run still shows its answer', async () => {
  api({ answers: [{ ...ANSWER, text: '知识库暂时不可用。', citations: [], unmatched: [] }] })
  renderApp('/?c=c1')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  act(() => {
    const s = MockEventSource.last()
    s.emit('step', step({ seq: 5, kind: 'tool', title: '搜索知识库', status: 'error', detail: '“报销” → 失败' }), '6')
    s.emit('end', {})
  })
  const timeline = screen.getByRole('complementary', { name: '执行过程' })
  const row = (await within(timeline).findByText('搜索知识库')).closest('li')
  expect(row).toHaveAttribute('data-status', 'error')
  expect(screen.getByText('知识库暂时不可用。')).toBeInTheDocument()
})

test('a new question reopens the stream after the newest step already shown', async () => {
  api()
  renderApp('/?c=c1')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  expect(MockEventSource.last().url).toMatch(/\/stream\?after=0$/)
  act(() => {
    MockEventSource.last().emit('step', step({ seq: 8, kind: 'finished', title: '完成' }), '8')
    MockEventSource.last().emit('end', {})
  })
  await ask('下一个问题')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(2))
  expect(MockEventSource.last().url).toMatch(/\/stream\?after=8$/)
})

test('a run that could not finish says so and frees Send', async () => {
  api()
  renderApp('/?c=c1')
  await openIdle()
  await ask('报销上限是多少？')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(2))
  await userEvent.setup().type(screen.getByLabelText('问题'), '再试一次')
  act(() => {
    MockEventSource.last().emit('failed', { run_id: 'r2', message: '这次回答没有完成，请重试。' })
    MockEventSource.last().emit('end', {})
  })
  expect(await screen.findByRole('alert')).toHaveTextContent('这次回答没有完成，请重试。')
  expect(screen.getByRole('button', { name: '发送' })).toBeEnabled()
})

test('a stream the browser gave up on frees Send and asks for a reload', async () => {
  api()
  renderApp('/?c=c1')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  await userEvent.setup().type(screen.getByLabelText('问题'), '问题')
  expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
  act(() => MockEventSource.last().fail())
  expect(await screen.findByRole('alert')).toHaveTextContent('连接中断，请刷新页面后重试。')
  expect(screen.getByRole('button', { name: '发送' })).toBeEnabled()
})

test('a failed answer shows a retry note instead of an empty box', async () => {
  api({ answers: [{ ...ANSWER, text: '', citations: [], unmatched: [], failed: true }] })
  renderApp('/?c=c1')
  await openIdle()
  expect(await screen.findByText('这次回答没有完成，请重试。')).toBeInTheDocument()
})

const CARD: CardOut = { id: 'k1', title: '报销时限', content: '报销要在 30 天内提交', risk_level: 'medium', reason: null }

test('a card from the stream asks whether to keep the knowledge', async () => {
  api()
  renderApp('/?c=c1')
  await waitFor(() => expect(MockEventSource.instances).toHaveLength(1))
  act(() => {
    MockEventSource.last().emit('suggestions', [CARD])
    MockEventSource.last().emit('end', {})
  })
  const card = await screen.findByRole('region', { name: '要不要存进知识库？' })
  expect(card).toHaveTextContent('报销要在 30 天内提交')
  expect(within(card).getByRole('button', { name: '存为团队知识' })).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: '只给我' })).toBeInTheDocument()
  expect(within(card).getByRole('button', { name: '不要' })).toBeInTheDocument()
})

test('存为团队知识 accepts for the team and the card goes away', async () => {
  let sent: unknown = null
  api({ cards: [CARD] })
  server.use(
    http.post('*/api/suggestions/k1/accept', async ({ request }) => {
      sent = await request.json()
      return HttpResponse.json({ status: 'accepted', entry_status: 'active' })
    }),
  )
  renderApp('/?c=c1')
  await openIdle()
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: '存为团队知识' }))
  await waitFor(() => expect(screen.queryByRole('region', { name: '要不要存进知识库？' })).toBeNull())
  expect(sent).toEqual({ scope: 'team' })
})

test('a card someone already decided (409) just goes away', async () => {
  api({ cards: [CARD] })
  server.use(
    http.post('*/api/suggestions/k1/reject', () =>
      HttpResponse.json({ detail: '已处理' }, { status: 409 }),
    ),
  )
  renderApp('/?c=c1')
  await openIdle()
  await userEvent.setup().click(await screen.findByRole('button', { name: '不要' }))
  await waitFor(() => expect(screen.queryByRole('region', { name: '要不要存进知识库？' })).toBeNull())
  expect(screen.queryByRole('alert')).toBeNull()
})

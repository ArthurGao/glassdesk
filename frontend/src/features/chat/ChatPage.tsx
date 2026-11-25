import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { createConversation, getAnswers, listConversations } from '@/client/sdk.gen'
import { AnswerFeedback } from './AnswerFeedback'
import { AnswerText } from './CitationChip'
import { Composer } from './Composer'
import { SuggestionCards } from './SuggestionCards'
import { chatKeys } from './keys'
import { TimelinePanel } from './TimelinePanel'
import { useStepStream } from './useStepStream'

const FAILED = '这次回答没有完成，请重试。'

export function ChatPage({ conversationId }: { conversationId?: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const conversations = useQuery({
    queryKey: chatKeys.conversations,
    queryFn: async () => (await listConversations({ throwOnError: true })).data,
  })
  const answers = useQuery({
    queryKey: chatKeys.answers(conversationId),
    queryFn: async () =>
      (await getAnswers({ path: { conversation_id: conversationId! }, throwOnError: true })).data,
    enabled: !!conversationId,
  })
  const { steps, streaming, problem, open } = useStepStream(conversationId)
  const [pending, setPending] = useState<string | null>(null)
  const shownPending = streaming ? pending : null

  async function onNew() {
    const { data } = await createConversation({ throwOnError: true })
    await queryClient.invalidateQueries({ queryKey: chatKeys.conversations })
    await navigate({ to: '/', search: { c: data.id } })
  }

  return (
    <div className="flex h-full">
      <nav aria-label="会话" className="w-56 border-r border-slate-200 bg-white p-2 text-sm">
        <button type="button" onClick={onNew} className="mb-2 w-full rounded border border-slate-300 py-1">
          + 新会话
        </button>
        <ul className="space-y-1">
          {conversations.data?.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() => navigate({ to: '/', search: { c: c.id } })}
                className={`w-full truncate rounded px-2 py-1 text-left ${c.id === conversationId ? 'bg-slate-100 font-medium' : ''}`}
              >
                {c.title}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <section className="flex min-w-0 flex-1 flex-col">
        {conversationId ? (
          <>
            <div className="flex-1 space-y-4 overflow-y-auto p-4 text-sm">
              {answers.data?.map((a) => (
                <article key={a.run_id} className="space-y-2">
                  <QuestionBubble text={a.question} />
                  <div className="max-w-[80%] rounded border border-slate-200 bg-white px-3 py-2">
                    {a.failed ? (
                      <p className="text-slate-500">{FAILED}</p>
                    ) : (
                      <>
                        <AnswerText answer={a} />
                        <AnswerFeedback conversationId={conversationId} answer={a} />
                      </>
                    )}
                  </div>
                </article>
              ))}
              {shownPending && (
                <QuestionBubble text={shownPending} />
              )}
            </div>
            <SuggestionCards />
            {problem && (
              <p role="alert" className="mx-3 mb-1 text-sm text-red-600">
                {problem}
              </p>
            )}
            <Composer
              conversationId={conversationId}
              busy={streaming}
              onAsked={(text) => {
                setPending(text)
                open()
              }}
            />
          </>
        ) : (
          <p className="p-6 text-slate-500">新建一个会话开始提问。</p>
        )}
      </section>
      <TimelinePanel steps={steps} />
    </div>
  )
}

function QuestionBubble({ text }: { text: string }) {
  return <p className="ml-auto w-fit max-w-[80%] rounded bg-slate-900 px-3 py-2 text-white">{text}</p>
}

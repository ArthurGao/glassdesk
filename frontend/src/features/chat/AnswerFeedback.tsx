import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { rateAnswer } from '@/client/sdk.gen'
import type { Answer } from '@/client/types.gen'
import { chatKeys } from './keys'

const CHOICES: Array<[boolean, string]> = [
  [true, '有帮助'],
  [false, '没帮助'],
]

/** Helpful / not helpful under an answer; the latest choice wins and shows pressed. */
export function AnswerFeedback({ conversationId, answer }: { conversationId: string; answer: Answer }) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)

  async function rate(helpful: boolean) {
    setSaving(true) // one rating at a time: a double click must not send two
    const { data } = await rateAnswer({
      path: { conversation_id: conversationId, run_id: answer.run_id },
      body: { helpful },
    }).finally(() => setSaving(false))
    if (!data) return
    queryClient.setQueryData<Answer[]>(chatKeys.answers(conversationId), (prev = []) =>
      prev.map((a) => (a.run_id === answer.run_id ? { ...a, feedback: data.helpful } : a)),
    )
  }

  const button = 'rounded px-2 py-0.5 text-xs text-slate-500 aria-pressed:bg-slate-200 aria-pressed:text-slate-900'
  return (
    <div className="mt-2 flex gap-1">
      {CHOICES.map(([helpful, label]) => (
        <button
          key={label}
          type="button"
          aria-pressed={answer.feedback === helpful}
          disabled={saving}
          onClick={() => rate(helpful)}
          className={button}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

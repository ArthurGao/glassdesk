import { useQueryClient } from '@tanstack/react-query'
import { rateAnswer } from '@/client/sdk.gen'
import type { Answer } from '@/client/types.gen'
import { chatKeys } from './keys'

/** Helpful / not helpful under an answer; the latest choice wins and shows pressed. */
export function AnswerFeedback({ conversationId, answer }: { conversationId: string; answer: Answer }) {
  const queryClient = useQueryClient()

  async function rate(helpful: boolean) {
    const { data } = await rateAnswer({
      path: { conversation_id: conversationId, run_id: answer.run_id },
      body: { helpful },
    })
    if (!data) return
    queryClient.setQueryData<Answer[]>(chatKeys.answers(conversationId), (prev = []) =>
      prev.map((a) => (a.run_id === answer.run_id ? { ...a, feedback: data.helpful } : a)),
    )
  }

  const button = 'rounded px-2 py-0.5 text-xs text-slate-500 aria-pressed:bg-slate-200 aria-pressed:text-slate-900'
  return (
    <div className="mt-2 flex gap-1">
      <button type="button" aria-pressed={answer.feedback === true} onClick={() => rate(true)} className={button}>
        有帮助
      </button>
      <button type="button" aria-pressed={answer.feedback === false} onClick={() => rate(false)} className={button}>
        没帮助
      </button>
    </div>
  )
}

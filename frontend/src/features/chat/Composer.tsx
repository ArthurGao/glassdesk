import { type FormEvent, type KeyboardEvent, useState } from 'react'
import { ask } from '@/client/sdk.gen'

export function Composer({
  conversationId,
  busy,
  onAsked,
  initialText = '',
}: {
  conversationId: string
  busy: boolean
  onAsked: (text: string) => void
  initialText?: string
}) {
  const [text, setText] = useState(initialText)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const question = text.trim()
    if (!question || busy) return
    setError(null)
    const { response } = await ask({
      path: { conversation_id: conversationId },
      body: { text: question },
    })
    if (response?.status === 202) {
      setText('')
      onAsked(question)
    } else if (response?.status === 409) {
      setError('上一个问题还在处理中')
    } else {
      setError('发送失败，请稍后再试')
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Enter sends, Shift+Enter is a new line; Enter that confirms an IME composition (pinyin) is
    // the input method's, not a send
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    event.currentTarget.form?.requestSubmit()
  }

  return (
    <form onSubmit={onSubmit} className="border-t border-slate-200 bg-white p-3">
      {error && (
        <p role="alert" className="mb-2 text-sm text-red-600">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <textarea
          aria-label="问题"
          className="min-h-10 flex-1 resize-none rounded border border-slate-300 px-2 py-1 text-sm"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="输入问题…（Enter 发送，Shift+Enter 换行）"
        />
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="rounded bg-slate-900 px-4 text-sm text-white disabled:opacity-50"
        >
          发送
        </button>
      </div>
    </form>
  )
}

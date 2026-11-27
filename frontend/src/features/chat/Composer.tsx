import { type FormEvent, type KeyboardEvent, useRef, useState } from 'react'
import { ask } from '@/client/sdk.gen'
import { useT } from '@/lib/i18n'

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
  const t = useT()
  const [text, setText] = useState(initialText)
  const [error, setError] = useState<string | null>(null)
  // the POST itself, before the stream (`busy`) starts: a ref, so a second Enter in the same
  // render cannot slip through
  const sending = useRef(false)
  const [sendingNow, setSendingNow] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const question = text.trim()
    if (!question || busy || sending.current) return
    sending.current = true
    setSendingNow(true)
    setError(null)
    const { response } = await ask({
      path: { conversation_id: conversationId },
      body: { text: question },
    }).finally(() => {
      sending.current = false
      setSendingNow(false)
    })
    if (response?.status === 202) {
      setText('')
      onAsked(question)
    } else if (response?.status === 409) {
      setError(t.chat.busy)
    } else {
      setError(t.chat.sendFailed)
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
          aria-label={t.chat.question}
          className="min-h-10 flex-1 resize-none rounded border border-slate-300 px-2 py-1 text-sm"
          value={text}
          maxLength={4000}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t.chat.placeholder}
        />
        <button
          type="submit"
          disabled={busy || sendingNow || !text.trim()}
          className="rounded bg-slate-900 px-4 text-sm text-white disabled:opacity-50"
        >
          {t.chat.send}
        </button>
      </div>
    </form>
  )
}

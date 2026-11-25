import { useEffect, useRef, useState } from 'react'
import type { Answer, Citation } from '@/client/types.gen'

function CitationChip({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  const root = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])
  return (
    <span ref={root} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mx-0.5 rounded bg-sky-100 px-1 text-xs text-sky-800 hover:bg-sky-200"
      >
        [{citation.n}]
      </button>
      {open && (
        <span
          role="dialog"
          aria-label={`引用 ${citation.n}`}
          className="absolute left-0 top-6 z-10 block w-72 rounded border border-slate-200 bg-white p-3 text-sm shadow-lg"
        >
          <span className="flex items-center gap-2 font-medium">
            {citation.title ?? (citation.kind === 'memory' ? '记忆' : '知识')}
            {citation.verified && (
              <span className="rounded bg-emerald-100 px-1 text-xs text-emerald-800">已验证</span>
            )}
          </span>
          <span className="mt-1 block text-slate-700">{citation.text}</span>
        </span>
      )}
    </span>
  )
}

/** The answer's text with `[n]` markers that a search backs turned into citation chips. */
export function AnswerText({ answer }: { answer: Answer }) {
  const byN = new Map(answer.citations.map((c) => [c.n, c]))
  const parts: Array<string | Citation> = []
  let plain = ''
  for (const piece of answer.text.split(/(\[\d+\])/)) {
    const marker = /^\[(\d+)\]$/.exec(piece)
    const citation = marker ? byN.get(Number(marker[1])) : undefined
    if (citation) {
      parts.push(plain, citation)
      plain = ''
    } else {
      plain += piece // unmatched markers stay plain text
    }
  }
  parts.push(plain)
  return (
    <p className="whitespace-pre-wrap">
      {parts.map((p, i) =>
        typeof p === 'string' ? p : <CitationChip key={`${p.n}-${i}`} citation={p} />,
      )}
    </p>
  )
}

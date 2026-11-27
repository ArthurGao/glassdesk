import { createContext, useContext, useEffect, useRef, useState } from 'react'
import Markdown, { type Components } from 'react-markdown'
import type { Answer, Citation } from '@/client/types.gen'
import { useT } from '@/lib/i18n'

function CitationChip({ citation }: { citation: Citation }) {
  const t = useT()
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
          aria-label={t.chat.citation(citation.n)}
          className="absolute left-0 top-6 z-10 block w-72 rounded border border-slate-200 bg-white p-3 text-sm shadow-lg"
        >
          <span className="flex items-center gap-2 font-medium">
            {citation.title ?? (citation.kind === 'memory' ? t.chat.memory : t.chat.knowledge)}
            {citation.verified && (
              <span className="rounded bg-emerald-100 px-1 text-xs text-emerald-800">{t.chat.verified}</span>
            )}
          </span>
          <span className="mt-1 block text-slate-700">{citation.text}</span>
        </span>
      )}
    </span>
  )
}

// The few hast fields the citation pass touches (react-markdown hands rehype plugins a hast tree).
type HastNode = {
  type: string
  value?: string
  tagName?: string
  properties?: Record<string, unknown>
  children?: HastNode[]
}

const MARKER = /\[(\d+)\]/g
const NOT_PROSE = new Set(['code', 'pre'])

/** A rehype pass that turns each `[n]` a search backs into a citation placeholder, wherever the
 * text sits (a paragraph, bold, a list item); code is left alone, unmatched markers stay text. */
function citations(known: ReadonlyMap<number, Citation>) {
  const split = (value: string): HastNode[] => {
    const out: HastNode[] = []
    let last = 0
    for (const m of value.matchAll(MARKER)) {
      const n = Number(m[1])
      if (!known.has(n)) continue
      if (m.index > last) out.push({ type: 'text', value: value.slice(last, m.index) })
      out.push({ type: 'element', tagName: 'span', properties: { dataCite: n }, children: [] })
      last = m.index + m[0].length
    }
    if (last < value.length) out.push({ type: 'text', value: value.slice(last) })
    return out
  }
  const walk = (node: HastNode) => {
    if (!node.children || NOT_PROSE.has(node.tagName ?? '')) return
    node.children = node.children.flatMap((child) => {
      if (child.type === 'text') return split(child.value ?? '')
      walk(child)
      return [child]
    })
  }
  return () => walk
}

const Cited = createContext<ReadonlyMap<number, Citation>>(new Map())

// Module-level, so a chip keeps its open state when the answer re-renders.
const components: Components = {
  // Markdown makes no spans of its own (raw HTML is not rendered): every span is a placeholder
  // `citations` made for a marker that `byN` backs.
  span: function CitationSpan({ node }) {
    const citation = useContext(Cited).get(Number(node?.properties.dataCite))
    return citation && <CitationChip citation={citation} />
  },
  // a single newline stays a line break (answers list things line by line); spaces still fold
  p: ({ children }) => <p className="whitespace-pre-line">{children}</p>,
  // Links are text with the URL shown: a URL in model text (steered by an injected passage) must
  // not become something to click that carries data out. A chip inside the text still works.
  a: function LinkAsText({ href, children }) {
    const same = typeof children === 'string' && children === href
    return <span>{children}{!same && href ? ` (${href})` : null}</span>
  },
}

/** The answer's text as Markdown (raw HTML is never rendered, images never loaded: a URL in
 * model text could carry data out), with the `[n]` markers that a search backs turned into
 * citation chips. */
export function AnswerText({ answer }: { answer: Answer }) {
  const byN = new Map(answer.citations.map((c) => [c.n, c]))
  return (
    <div className="space-y-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ul]:list-disc [&_ul]:pl-5">
      <Cited.Provider value={byN}>
        <Markdown
          rehypePlugins={[citations(byN)]}
          components={components}
          disallowedElements={['img']}
          // no URL ever becomes an attribute (links are text, images dropped), so show it as written
          urlTransform={(url) => url}
        >
          {answer.text}
        </Markdown>
      </Cited.Provider>
    </div>
  )
}

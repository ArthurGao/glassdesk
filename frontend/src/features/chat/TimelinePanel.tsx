import { CircleAlert, CircleCheck, LoaderCircle } from 'lucide-react'
import type { Step, Usage } from '@/client/types.gen'

const tokens = (u: Usage) => (u.input ?? 0) + (u.output ?? 0)
const secs = (ms: number) => `${(ms / 1000).toFixed(1)}s`

function formatCost(cost: number | null | undefined) {
  return cost == null ? '未知' : `$${cost.toFixed(4)}`
}

const ICON = {
  running: <LoaderCircle className="size-4 animate-spin text-sky-600" aria-hidden />,
  ok: <CircleCheck className="size-4 text-emerald-600" aria-hidden />,
  error: <CircleAlert className="size-4 text-red-600" aria-hidden />,
}

/** The latest run's steps, as the agent took them (design §6). */
export function TimelinePanel({ steps }: { steps: Step[] }) {
  const lastRun = steps.at(-1)?.run_id
  const shown = steps.filter((s) => s.run_id === lastRun)
  const finished = shown.find((s) => s.kind === 'finished')
  return (
    <aside aria-label="执行过程" className="flex w-80 flex-col border-l border-slate-200 bg-white">
      <h2 className="border-b border-slate-200 px-4 py-2 text-sm font-medium">执行过程</h2>
      {shown.length === 0 ? (
        <p className="p-4 text-sm text-slate-500">提问后，这里会显示助手的每一步。</p>
      ) : (
        <ol className="flex-1 space-y-2 overflow-y-auto p-4 text-sm">
          {shown.map((s) => (
            <li key={s.seq} data-status={s.status} className="flex gap-2 data-[status=error]:text-red-700">
              {ICON[s.status]}
              <div className="min-w-0">
                <div className="font-medium">{s.title}</div>
                {s.detail && <div className="truncate text-slate-500">{s.detail}</div>}
                <div className="text-xs text-slate-400">
                  {s.duration_ms != null && secs(s.duration_ms)}
                  {s.kind !== 'finished' && s.usage && ` · ${tokens(s.usage)} tokens`}
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
      {finished && (
        <div className="border-t border-slate-200 px-4 py-2 text-xs text-slate-600">
          <span>{finished.usage ? tokens(finished.usage) : '?'} tokens</span> · <span>成本 {formatCost(finished.usage?.cost_usd)}</span>
          {finished.duration_ms != null && ` · 总耗时 ${secs(finished.duration_ms)}`}
        </div>
      )}
    </aside>
  )
}

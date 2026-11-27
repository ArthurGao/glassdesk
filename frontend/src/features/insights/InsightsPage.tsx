import { useQuery } from '@tanstack/react-query'
import { insights } from '@/client/sdk.gen'
import type { DayOut } from '@/client/types.gen'
import { label, type Messages, useT } from '@/lib/i18n'
import { insightsKeys } from './keys'

/** Unknown cost is never 0: all unknown shows "unknown"; some unknown shows the known sum and how
 * many runs did not report one. */
function cost(d: DayOut, t: Messages): string {
  if (d.cost_usd == null) return d.answers ? t.unknown : '—'
  const known = '$' + d.cost_usd.toFixed(4)
  return d.cost_unknown_runs ? known + t.insights.unknownRuns(d.cost_unknown_runs) : known
}


/** Known tokens, with how many runs reported none (they are not in the number). */
function tokens(d: DayOut, t: Messages): string {
  const known = d.tokens.toLocaleString()
  return d.tokens_unknown_runs ? known + t.insights.unknownRuns(d.tokens_unknown_runs) : known
}

export function InsightsPage() {
  const tr = useT()
  const query = useQuery({
    queryKey: insightsKeys.all,
    queryFn: async () => {
      const { data, response } = await insights()
      if (response?.status === 403) return 'forbidden' as const
      if (!data) throw new Error('insights answered ' + (response?.status ?? 'no response'))
      return data
    },
  })
  if (query.isError) {
    return (
      <p role="alert" className="p-6 text-red-600">
        {tr.insights.loadFailed}
      </p>
    )
  }
  if (query.data === 'forbidden') return <p className="p-6 text-slate-500">{tr.insights.forbidden}</p>
  const body = query.data
  if (!body) return <p className="p-6 text-slate-500">{tr.loading}</p>
  const t = body.totals
  const rate = body.helpful_rate == null ? '—' : Math.round(body.helpful_rate * 100) + '%' + tr.insights.rated(body.rated)
  const tiles: Array<[string, string]> = [
    [tr.insights.answers, String(t.answers)],
    [tr.insights.failed, String(t.failed)],
    ['tokens', tokens(t, tr)],
    [tr.insights.cost, cost(t, tr)],
    [tr.insights.helpfulRate, rate],
  ]
  return (
    <div className="h-full space-y-6 overflow-y-auto p-6 text-sm">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">{tr.insights.lastWeek}</h1>
        {body.demo && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">{tr.insights.demo}</span>}
      </div>
      <ul aria-label={tr.insights.overview} className="grid grid-cols-5 gap-3">
        {tiles.map(([label, value]) => (
          <li key={label} className="rounded border border-slate-200 bg-white p-3">
            <div className="text-slate-500">{label}</div>
            <div className="mt-1 text-lg font-medium">{value}</div>
          </li>
        ))}
      </ul>
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">{tr.insights.day}</th><th className="p-2">{tr.insights.answers}</th><th className="p-2">{tr.insights.failed}</th><th className="p-2">tokens</th><th className="p-2">{tr.insights.cost}</th></tr>
        </thead>
        <tbody>
          {body.days.map((d) => (
            <tr key={d.day} className="border-t border-slate-100">
              <td className="p-2">{d.day}</td>
              <td className="p-2">{d.answers}</td>
              <td className="p-2">{d.failed}</td>
              <td className="p-2">{tokens(d, tr)}</td>
              <td className="p-2">{cost(d, tr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="space-y-2">
        <h2 className="font-medium">{tr.insights.kb}</h2>
        {body.kb ? (
          <>
            <p className="text-slate-600">
              {Object.entries(body.kb.entries_by_status).map(([s, n]) => label(tr.entryStatus, s) + ' ' + n).join(' · ')}
              {' · '}<span>{tr.insights.pendingReviews} {body.kb.pending_reviews}</span>{' · '}{tr.insights.awaitingUser} {body.kb.awaiting_user}
            </p>
            <h3 className="text-slate-500">{tr.insights.gaps}</h3>
            <ul className="list-disc pl-5">
              {body.kb.gaps.map((g) => (
                <li key={g.query}><span>{g.query}</span> <span className="text-slate-400">×{g.count}</span></li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-slate-500">{tr.insights.kbNotConfigured}</p>
        )}
      </section>
    </div>
  )
}

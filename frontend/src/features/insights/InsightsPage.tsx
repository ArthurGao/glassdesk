import { useQuery } from '@tanstack/react-query'
import { insights } from '@/client/sdk.gen'
import type { DayOut } from '@/client/types.gen'
import { ENTRY_STATUS } from '@/lib/labels'
import { insightsKeys } from './keys'

/** Unknown cost is never 0: all unknown shows "unknown"; some unknown shows the known sum and how
 * many runs did not report one. */
function cost(d: DayOut): string {
  if (d.cost_usd == null) return d.answers ? '未知' : '—'
  const known = '$' + d.cost_usd.toFixed(4)
  return d.cost_unknown_runs ? known + '（' + d.cost_unknown_runs + ' 次未知）' : known
}


export function InsightsPage() {
  const query = useQuery({
    queryKey: insightsKeys.all,
    queryFn: async () => {
      const { data, response } = await insights()
      if (response?.status === 403) return 'forbidden' as const
      if (!data) throw new Error('insights answered ' + (response?.status ?? 'no response'))
      return data
    },
  })
  if (query.data === 'forbidden') return <p className="p-6 text-slate-500">需要审核权限才能查看洞察。</p>
  const body = query.data
  if (!body) return null
  const t = body.totals
  const rate = body.helpful_rate == null ? '—' : Math.round(body.helpful_rate * 100) + '%（' + body.rated + ' 次评价）'
  const tiles: Array<[string, string]> = [
    ['回答', String(t.answers)],
    ['失败', String(t.failed)],
    ['tokens', t.tokens.toLocaleString()],
    ['成本', cost(t)],
    ['好评率', rate],
  ]
  return (
    <div className="h-full space-y-6 overflow-y-auto p-6 text-sm">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">最近 7 天</h1>
        {body.demo && <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">演示数据</span>}
      </div>
      <ul aria-label="概览" className="grid grid-cols-5 gap-3">
        {tiles.map(([label, value]) => (
          <li key={label} className="rounded border border-slate-200 bg-white p-3">
            <div className="text-slate-500">{label}</div>
            <div className="mt-1 text-lg font-medium">{value}</div>
          </li>
        ))}
      </ul>
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">日期</th><th className="p-2">回答</th><th className="p-2">失败</th><th className="p-2">tokens</th><th className="p-2">成本</th></tr>
        </thead>
        <tbody>
          {body.days.map((d) => (
            <tr key={d.day} className="border-t border-slate-100">
              <td className="p-2">{d.day}</td>
              <td className="p-2">{d.answers}</td>
              <td className="p-2">{d.failed}</td>
              <td className="p-2">{d.tokens.toLocaleString()}</td>
              <td className="p-2">{cost(d)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <section className="space-y-2">
        <h2 className="font-medium">知识库</h2>
        {body.kb ? (
          <>
            <p className="text-slate-600">
              {Object.entries(body.kb.entries_by_status).map(([s, n]) => (ENTRY_STATUS[s] ?? s) + ' ' + n).join(' · ')}
              {' · '}<span>待审核 {body.kb.pending_reviews}</span>{' · '}待确认 {body.kb.awaiting_user}
            </p>
            <h3 className="text-slate-500">知识库缺什么（检索不到好结果的问题）</h3>
            <ul className="list-disc pl-5">
              {body.kb.gaps.map((g) => (
                <li key={g.query}><span>{g.query}</span> <span className="text-slate-400">×{g.count}</span></li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-slate-500">知识库统计未配置</p>
        )}
      </section>
    </div>
  )
}

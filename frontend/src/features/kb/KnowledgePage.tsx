import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import {
  approve,
  createEntry,
  listDocuments,
  listEntries,
  listReviews,
  reject,
  uploadDocument,
} from '@/client/sdk.gen'
import { isSettled } from '@/lib/api'
import { ENTRY_STATUS } from '@/lib/labels'
import { meQuery } from '@/lib/session'
import { kbKeys } from './keys'


const DOC_STATUS: Record<string, string> = {
  pending: '等待处理', processing: '处理中', ready: '可检索', failed: '处理失败',
}
const RISK: Record<string, string> = { low: '低', medium: '中', high: '高' }

type Tab = 'entries' | 'documents' | 'reviews'

export function KnowledgePage() {
  const { data: me } = useQuery(meQuery)
  const canReview = me?.role === 'reviewer' || me?.role === 'admin'
  const [tab, setTab] = useState<Tab>('entries')
  const tabs: Array<[Tab, string]> = [['entries', '条目'], ['documents', '文档']]
  if (canReview) tabs.push(['reviews', '待审核'])
  return (
    <div className="h-full overflow-y-auto p-6">
      <div role="tablist" className="mb-4 flex gap-4 border-b border-slate-200 text-sm">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            role="tab"
            type="button"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className="-mb-px border-b-2 border-transparent px-1 pb-2 aria-selected:border-slate-900 aria-selected:font-medium"
          >
            {label}
          </button>
        ))}
      </div>
      {tab === 'entries' && <Entries />}
      {tab === 'documents' && <Documents />}
      {tab === 'reviews' && canReview && <Reviews />}
    </div>
  )
}

function Entries() {
  const queryClient = useQueryClient()
  const entries = useQuery({
    queryKey: kbKeys.entries,
    queryFn: async () => (await listEntries({ throwOnError: true })).data,
  })
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    const { data, response } = await createEntry({ body: { title, content } })
    if (!data) {
      setNotice(response?.status === 503 ? '知识库暂时不可用' : '保存失败，请检查内容后重试')
      return
    }
    setNotice(data.entry ? '已存入知识库' : '已提交审核：高风险内容需要审核员批准后生效')
    setTitle('')
    setContent('')
    setOpen(false)
    // a candidate is not an entry yet: the list only changes when one went live
    if (data.entry) await queryClient.invalidateQueries({ queryKey: kbKeys.entries })
  }

  return (
    <section className="space-y-3 text-sm">
      <div className="flex items-center gap-3">
        <button type="button" onClick={() => setOpen((v) => !v)} className="rounded bg-slate-900 px-3 py-1 text-white">
          新建条目
        </button>
        {notice && <p role="status" className="text-slate-600">{notice}</p>}
      </div>
      {open && (
        <form onSubmit={onSubmit} className="space-y-2 rounded border border-slate-200 bg-white p-3">
          <label className="block">
            标题
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label className="block">
            内容
            <textarea className="mt-1 min-h-24 w-full rounded border border-slate-300 px-2 py-1" value={content} maxLength={20000} onChange={(e) => setContent(e.target.value)} required />
          </label>
          <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-white">保存</button>
        </form>
      )}
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">标题</th><th className="p-2">状态</th><th className="p-2">风险</th><th className="p-2">命中</th></tr>
        </thead>
        <tbody>
          {entries.data?.map((e) => (
            <tr key={e.id} className="border-t border-slate-100">
              <td className="p-2"><div className="font-medium">{e.title}</div><div className="line-clamp-2 text-slate-500">{e.content}</div></td>
              <td className="p-2">{ENTRY_STATUS[e.status] ?? e.status}</td>
              <td className="p-2">{RISK[e.risk_level] ?? e.risk_level}</td>
              <td className="p-2">{e.hit_count ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Documents() {
  const queryClient = useQueryClient()
  const documents = useQuery({
    queryKey: kbKeys.documents,
    queryFn: async () => (await listDocuments({ throwOnError: true })).data,
  })
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    const { data, error } = await uploadDocument({ body: { file, title: title || null } })
    if (!data) {
      const detail = (error as { detail?: unknown } | undefined)?.detail
      setNotice(typeof detail === 'string' ? detail : '上传失败，请稍后再试')
      return
    }
    setNotice(data.candidate ? '已上传，等待审核' : '已上传，正在处理')
    setFile(null)
    setTitle('')
    await queryClient.invalidateQueries({ queryKey: kbKeys.documents })
  }

  return (
    <section className="space-y-3 text-sm">
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
        <label className="block">
          文件
          <input type="file" accept=".pdf,.docx,.md,.txt,.html" className="mt-1 block" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="block">
          标题（可选）
          <input className="mt-1 block rounded border border-slate-300 px-2 py-1" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <button type="submit" disabled={!file} className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50">上传</button>
        {notice && <p role="status" className="text-slate-600">{notice}</p>}
      </form>
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">标题</th><th className="p-2">文件</th><th className="p-2">状态</th></tr>
        </thead>
        <tbody>
          {documents.data?.map((d) => (
            <tr key={d.id} className="border-t border-slate-100">
              <td className="p-2 font-medium">{d.title}</td>
              <td className="p-2 text-slate-500">{d.filename}</td>
              <td className="p-2">{DOC_STATUS[d.status] ?? d.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Reviews() {
  const queryClient = useQueryClient()
  const reviews = useQuery({
    queryKey: kbKeys.reviews,
    queryFn: async () => (await listReviews({ throwOnError: true })).data,
  })
  const [error, setError] = useState<string | null>(null)

  async function decide(id: string, ok: boolean) {
    setError(null)
    const call = ok ? approve : reject
    const { response } = await call({ path: { candidate_id: id }, body: { note: null } })
    if (!isSettled(response)) {
      setError('操作失败，请稍后再试')
      return
    }
    await queryClient.invalidateQueries({ queryKey: kbKeys.reviews })
    await queryClient.invalidateQueries({ queryKey: kbKeys.entries })
  }

  if (reviews.data?.length === 0) return <p className="text-sm text-slate-500">没有待审核的内容。</p>
  return (
    <section className="space-y-2 text-sm">
      {error && <p role="alert" className="text-red-600">{error}</p>}
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">内容</th><th className="p-2">风险</th><th className="p-2">原因</th><th className="p-2" /></tr>
        </thead>
        <tbody>
          {reviews.data?.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td className="p-2"><div className="font-medium">{r.title}</div><div className="text-slate-500">{r.content}</div></td>
              <td className="p-2">{RISK[r.risk_level] ?? r.risk_level}</td>
              <td className="p-2 text-slate-500">{r.reason ?? '—'}</td>
              <td className="space-x-2 p-2 text-right">
                <button type="button" onClick={() => decide(r.id, true)} className="rounded bg-slate-900 px-2 py-1 text-white">批准</button>
                <button type="button" onClick={() => decide(r.id, false)} className="rounded border border-slate-300 px-2 py-1">拒绝</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

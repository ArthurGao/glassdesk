import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import type { EntryOut } from '@/client/types.gen'
import {
  approve,
  createEntry,
  deprecateEntry,
  listDocuments,
  listEntries,
  listReviews,
  reject,
  uploadDocument,
} from '@/client/sdk.gen'
import { ConfirmDialog } from '@/components/ConfirmDialog'
import { isSettled } from '@/lib/api'
import { label, useT } from '@/lib/i18n'
import { meQuery } from '@/lib/session'
import { kbKeys } from './keys'


type Tab = 'entries' | 'documents' | 'reviews'

export function KnowledgePage() {
  const { data: me } = useQuery(meQuery)
  const t = useT()
  const canReview = me?.role === 'reviewer' || me?.role === 'admin'
  const [tab, setTab] = useState<Tab>('entries')
  const tabs: Array<[Tab, string]> = [['entries', t.kb.entries], ['documents', t.kb.documents]]
  if (canReview) tabs.push(['reviews', t.kb.reviews])
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
      {tab === 'entries' && <Entries canReview={canReview} />}
      {tab === 'documents' && <Documents />}
      {tab === 'reviews' && canReview && <Reviews />}
    </div>
  )
}

function Entries({ canReview }: { canReview: boolean }) {
  const queryClient = useQueryClient()
  const t = useT()
  const entries = useQuery({
    queryKey: kbKeys.entries,
    queryFn: async () => (await listEntries({ throwOnError: true })).data,
  })
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  // steward judges the entry's risk with a model before it answers (tens of seconds locally)
  const [saving, setSaving] = useState(false)
  const [deprecating, setDeprecating] = useState<EntryOut | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    const { data, response } = await createEntry({ body: { title, content } }).finally(() =>
      setSaving(false),
    )
    if (!data) {
      setNotice(response?.status === 503 ? t.kb.unavailable : t.kb.saveFailed)
      return
    }
    setNotice(data.entry ? t.kb.saved : t.kb.sentToReview)
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
          {t.kb.newEntry}
        </button>
        {notice && <p role="status" className="text-slate-600">{notice}</p>}
      </div>
      {open && (
        <form onSubmit={onSubmit} className="space-y-2 rounded border border-slate-200 bg-white p-3">
          <label className="block">
            {t.kb.title}
            <input className="mt-1 w-full rounded border border-slate-300 px-2 py-1" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} required />
          </label>
          <label className="block">
            {t.kb.content}
            <textarea className="mt-1 min-h-24 w-full rounded border border-slate-300 px-2 py-1" value={content} maxLength={20000} onChange={(e) => setContent(e.target.value)} required />
          </label>
          <button type="submit" disabled={saving} className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50">
            {saving ? t.kb.saving : t.kb.save}
          </button>
        </form>
      )}
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">{t.kb.title}</th><th className="p-2">{t.kb.status}</th><th className="p-2">{t.kb.risk}</th><th className="p-2">{t.kb.hits}</th>{canReview && <th className="p-2" />}</tr>
        </thead>
        <tbody>
          {entries.data?.map((e) => (
            <tr key={e.id} className="border-t border-slate-100">
              <td className="p-2"><div className="font-medium">{e.title}</div><div className="line-clamp-2 text-slate-500">{e.content}</div></td>
              <td className="p-2">{label(t.entryStatus, e.status)}</td>
              <td className="p-2">{label(t.kb.riskLevel, e.risk_level)}</td>
              <td className="p-2">{e.hit_count ?? '—'}</td>
              {canReview && (
                <td className="p-2 text-right">
                  {e.status !== 'deprecated' && (
                    <button type="button" onClick={() => setDeprecating(e)} className="rounded border border-slate-300 px-2 py-1">
                      {t.kb.deprecate}
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {deprecating && <DeprecateDialog entry={deprecating} onClose={() => setDeprecating(null)} />}
    </section>
  )
}

function DeprecateDialog({ entry, onClose }: { entry: EntryOut; onClose: () => void }) {
  const queryClient = useQueryClient()
  const t = useT()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onConfirm() {
    setBusy(true)
    setError(null)
    const { response } = await deprecateEntry({
      path: { entry_id: entry.id },
      body: { reason: reason.trim() || null },
    }).finally(() => setBusy(false))
    // 404 / 409: gone or deprecated meanwhile; the refetch shows what it is now
    if (!isSettled(response)) {
      setError(t.actionFailed)
      return
    }
    await queryClient.invalidateQueries({ queryKey: kbKeys.entries })
    onClose()
  }

  return (
    <ConfirmDialog
      title={t.kb.deprecateTitle}
      confirmLabel={busy ? t.kb.deprecating : t.kb.deprecate}
      busy={busy}
      error={error}
      onConfirm={onConfirm}
      onCancel={onClose}
    >
      <p className="text-slate-700">{t.kb.deprecateBody(entry.title)}</p>
      <label className="block">
        {t.kb.deprecateReason}
        <textarea className="mt-1 min-h-16 w-full rounded border border-slate-300 px-2 py-1" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </label>
    </ConfirmDialog>
  )
}

function Documents() {
  const queryClient = useQueryClient()
  const t = useT()
  const documents = useQuery({
    queryKey: kbKeys.documents,
    queryFn: async () => (await listDocuments({ throwOnError: true })).data,
  })
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!file || uploading) return
    setUploading(true)
    const { data, error } = await uploadDocument({ body: { file, title: title || null } }).finally(
      () => setUploading(false),
    )
    if (!data) {
      const detail = (error as { detail?: unknown } | undefined)?.detail
      setNotice(typeof detail === 'string' ? detail : t.kb.uploadFailed)
      return
    }
    setNotice(data.candidate ? t.kb.uploadedForReview : t.kb.uploadedProcessing)
    setFile(null)
    setTitle('')
    await queryClient.invalidateQueries({ queryKey: kbKeys.documents })
  }

  return (
    <section className="space-y-3 text-sm">
      <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-2">
        <label className="block">
          {t.kb.file}
          <input type="file" accept=".pdf,.docx,.md,.txt,.html" className="mt-1 block" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="block">
          {t.kb.titleOptional}
          <input className="mt-1 block rounded border border-slate-300 px-2 py-1" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <button type="submit" disabled={!file || uploading} className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50">
          {uploading ? t.kb.uploading : t.kb.upload}
        </button>
        {notice && <p role="status" className="text-slate-600">{notice}</p>}
      </form>
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">{t.kb.title}</th><th className="p-2">{t.kb.file}</th><th className="p-2">{t.kb.status}</th></tr>
        </thead>
        <tbody>
          {documents.data?.map((d) => (
            <tr key={d.id} className="border-t border-slate-100">
              <td className="p-2 font-medium">{d.title}</td>
              <td className="p-2 text-slate-500">{d.filename}</td>
              <td className="p-2">{label(t.kb.docStatus, d.status)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function Reviews() {
  const queryClient = useQueryClient()
  const t = useT()
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
      setError(t.actionFailed)
      return
    }
    await queryClient.invalidateQueries({ queryKey: kbKeys.reviews })
    await queryClient.invalidateQueries({ queryKey: kbKeys.entries })
  }

  if (reviews.data?.length === 0) return <p className="text-sm text-slate-500">{t.kb.noReviews}</p>
  return (
    <section className="space-y-2 text-sm">
      {error && <p role="alert" className="text-red-600">{error}</p>}
      <table className="w-full bg-white">
        <thead className="text-left text-slate-500">
          <tr><th className="p-2">{t.kb.content}</th><th className="p-2">{t.kb.risk}</th><th className="p-2">{t.kb.reason}</th><th className="p-2" /></tr>
        </thead>
        <tbody>
          {reviews.data?.map((r) => (
            <tr key={r.id} className="border-t border-slate-100">
              <td className="p-2"><div className="font-medium">{r.title}</div><div className="text-slate-500">{r.content}</div></td>
              <td className="p-2">{label(t.kb.riskLevel, r.risk_level)}</td>
              <td className="p-2 text-slate-500">{r.reason ?? '—'}</td>
              <td className="space-x-2 p-2 text-right">
                <button type="button" onClick={() => decide(r.id, true)} className="rounded bg-slate-900 px-2 py-1 text-white">{t.kb.approve}</button>
                <button type="button" onClick={() => decide(r.id, false)} className="rounded border border-slate-300 px-2 py-1">{t.kb.reject}</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

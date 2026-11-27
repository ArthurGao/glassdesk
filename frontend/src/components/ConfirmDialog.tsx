import { type ReactNode, useEffect, useId, useRef } from 'react'
import { useT } from '@/lib/i18n'

/** The app's confirmation dialog (never window.confirm): a modal with a title, a body, and
 * confirm / cancel. Escape or a click on the backdrop cancels, unless the action is running. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  cancelLabel,
  busy = false,
  error,
  onConfirm,
  onCancel,
}: {
  title: string
  children: ReactNode
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  error?: string | null
  onConfirm: () => void
  onCancel: () => void
}) {
  const t = useT()
  const titleId = useId()
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>('textarea, input, button')?.focus()
  }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onCancel()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onCancel])
  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-slate-900/30"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-96 max-w-[calc(100%-2rem)] space-y-3 rounded border border-slate-200 bg-white p-4 text-sm shadow-lg"
      >
        <h2 id={titleId} className="font-medium">{title}</h2>
        {children}
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={busy} className="rounded border border-slate-300 px-3 py-1 disabled:opacity-50">
            {cancelLabel ?? t.cancel}
          </button>
          <button type="button" onClick={onConfirm} disabled={busy} className="rounded bg-red-700 px-3 py-1 text-white disabled:opacity-50">
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

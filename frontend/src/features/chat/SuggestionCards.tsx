import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { acceptCard, listCards, rejectCard } from '@/client/sdk.gen'
import type { CardOut } from '@/client/types.gen'
import { isSettled } from '@/lib/api'
import { useT } from '@/lib/i18n'
import { chatKeys } from './keys'

/** steward's open confirmation cards for this user: keep for the team, for me, or not at all. */
export function SuggestionCards() {
  const queryClient = useQueryClient()
  const t = useT()
  const cards = useQuery({
    queryKey: chatKeys.suggestions,
    queryFn: async () => (await listCards({ throwOnError: true })).data,
    staleTime: 60_000, // the stream pushes new cards; no refetch on every focus
  })
  const [error, setError] = useState<string | null>(null)

  async function decide(card: CardOut, choice: 'team' | 'personal' | 'reject') {
    setError(null)
    const path = { card_id: card.id }
    const { response } =
      choice === 'reject'
        ? await rejectCard({ path })
        : await acceptCard({ path, body: { scope: choice } })
    if (isSettled(response)) {
      queryClient.setQueryData<CardOut[]>(chatKeys.suggestions, (prev = []) =>
        prev.filter((c) => c.id !== card.id),
      )
    } else {
      setError(t.actionFailed)
    }
  }

  if (!cards.data?.length) return null
  return (
    <div className="space-y-2 px-4 pb-2">
      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}
      {cards.data.map((card) => (
        <section
          key={card.id}
          aria-label={t.chat.cardQuestion}
          className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"
        >
          <p className="font-medium">{t.chat.cardQuestion}</p>
          <p className="mt-1">
            <span className="font-medium">{card.title}</span>
            {card.content !== card.title && <span className="text-slate-700">{t.chat.cardSeparator}{card.content}</span>}
          </p>
          <div className="mt-2 flex gap-2">
            <button type="button" onClick={() => decide(card, 'team')} className="rounded bg-slate-900 px-2 py-1 text-white">
              {t.chat.keepForTeam}
            </button>
            <button type="button" onClick={() => decide(card, 'personal')} className="rounded border border-slate-300 px-2 py-1">
              {t.chat.keepForMe}
            </button>
            <button type="button" onClick={() => decide(card, 'reject')} className="rounded px-2 py-1 text-slate-500">
              {t.chat.discard}
            </button>
          </div>
        </section>
      ))}
    </div>
  )
}

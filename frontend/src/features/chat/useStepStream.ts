import { type QueryClient, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useSyncExternalStore } from 'react'
import type { Answer, Step } from '@/client/types.gen'
import { chatKeys } from './keys'

type Snapshot = { steps: Step[]; streaming: boolean }

/**
 * One conversation's stream, outside React: `step` events upsert by `seq` (a tool step is sent
 * again when its result lands), `answer` goes straight into the answers cache, `end` closes it.
 * The browser resumes with Last-Event-ID on a dropped connection; `end` is what stops it from
 * reconnecting after a finished run.
 */
class StepStream {
  private source: EventSource | null = null
  private steps = new Map<number, Step>()
  private cursor = 0 // the newest stream id seen: where a reopened stream picks up
  private snapshot: Snapshot = { steps: [], streaming: false }
  private listeners = new Set<() => void>()

  constructor(
    private readonly conversationId: string,
    private readonly queryClient: QueryClient,
  ) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  getSnapshot = () => this.snapshot

  private publish(streaming: boolean) {
    this.snapshot = { steps: [...this.steps.values()].sort((a, b) => a.seq - b.seq), streaming }
    for (const listener of this.listeners) listener()
  }

  open = () => {
    this.source?.close()
    const id = this.conversationId
    // after the newest event already shown: reopening for a new question replays nothing
    const es = new EventSource(`/api/conversations/${id}/stream?after=${this.cursor}`, {
      withCredentials: true,
    })
    this.source = es
    es.addEventListener('step', (e: MessageEvent<string>) => {
      const step = JSON.parse(e.data) as Step
      this.steps.set(step.seq, step)
      if (e.lastEventId) this.cursor = Math.max(this.cursor, Number(e.lastEventId))
      this.publish(true)
    })
    es.addEventListener('answer', (e: MessageEvent<string>) => {
      const answer = JSON.parse(e.data) as Answer
      this.queryClient.setQueryData<Answer[]>(chatKeys.answers(id), (prev = []) => [
        ...prev.filter((a) => a.run_id !== answer.run_id),
        answer,
      ])
    })
    es.addEventListener('end', () => {
      this.close() // the answer is already in the cache; titles and order may have changed
      void this.queryClient.invalidateQueries({ queryKey: chatKeys.conversations })
    })
    this.publish(true)
  }

  close = () => {
    this.source?.close()
    this.source = null
    if (this.snapshot.streaming) this.publish(false)
  }
}

const IDLE: Snapshot = { steps: [], streaming: false }
const NONE = { subscribe: () => () => {}, getSnapshot: () => IDLE, open: () => {}, close: () => {} }

export function useStepStream(conversationId: string | undefined) {
  const queryClient = useQueryClient()
  const stream = useMemo(
    () => (conversationId ? new StepStream(conversationId, queryClient) : NONE),
    [conversationId, queryClient],
  )
  const { steps, streaming } = useSyncExternalStore(stream.subscribe, stream.getSnapshot)
  useEffect(() => {
    stream.open() // attach: replays the conversation's steps, follows a run still going
    return stream.close
  }, [stream])
  return { steps, streaming, open: stream.open }
}

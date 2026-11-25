/** A controllable stand-in for the browser's EventSource (jsdom has none). */
export class MockEventSource {
  static instances: MockEventSource[] = []
  static last(): MockEventSource {
    const last = MockEventSource.instances.at(-1)
    if (!last) throw new Error('no EventSource was opened')
    return last
  }

  readonly url: string
  closed = false
  private listeners = new Map<string, Array<(e: MessageEvent) => void>>()

  constructor(url: string | URL) {
    this.url = String(url)
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  removeEventListener() {}

  close() {
    this.closed = true
  }

  /** Deliver one server-sent event, as the browser would. */
  emit(type: string, data: unknown, id?: string) {
    const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id ?? '' })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

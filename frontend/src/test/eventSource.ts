/** A controllable stand-in for the browser's EventSource (jsdom has none). */
export class MockEventSource {
  static instances: MockEventSource[] = []
  static last(): MockEventSource {
    const last = MockEventSource.instances.at(-1)
    if (!last) throw new Error('no EventSource was opened')
    return last
  }

  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2

  readonly url: string
  closed = false
  readyState = MockEventSource.OPEN
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
    this.readyState = MockEventSource.CLOSED
  }

  /** The browser gave up on the stream (a non-200 such as 401): `error`, and it stays closed. */
  fail() {
    this.readyState = MockEventSource.CLOSED
    for (const listener of this.listeners.get('error') ?? []) listener(new MessageEvent('error'))
  }

  /** Deliver one server-sent event, as the browser would. */
  emit(type: string, data: unknown, id?: string) {
    const event = new MessageEvent(type, { data: JSON.stringify(data), lastEventId: id ?? '' })
    for (const listener of this.listeners.get(type) ?? []) listener(event)
  }
}

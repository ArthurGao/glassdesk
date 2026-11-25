import { createFileRoute } from '@tanstack/react-router'
import { ChatPage } from '@/features/chat/ChatPage'

export const Route = createFileRoute('/')({
  validateSearch: (search: Record<string, unknown>): { c?: string } =>
    typeof search.c === 'string' ? { c: search.c } : {},
  component: function Chat() {
    const { c } = Route.useSearch()
    return <ChatPage conversationId={c} />
  },
})

/** The chat's query keys, in one place so an invalidation always names what a query cached. */
export const chatKeys = {
  conversations: ['conversations'] as const,
  answers: (conversationId: string | undefined) => ['answers', conversationId] as const,
}

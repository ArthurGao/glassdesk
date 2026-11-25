import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/knowledge')({
  component: () => <p className="p-6 text-slate-500">知识库：即将推出</p>,
})

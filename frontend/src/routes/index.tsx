import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/')({
  component: () => <p className="p-6 text-slate-500">聊天：即将推出</p>,
})

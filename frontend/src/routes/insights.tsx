import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/insights')({
  component: () => <p className="p-6 text-slate-500">洞察：即将推出</p>,
})

import { createFileRoute } from '@tanstack/react-router'
import { KnowledgePage } from '@/features/kb/KnowledgePage'

export const Route = createFileRoute('/knowledge')({ component: KnowledgePage })

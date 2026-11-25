// The client is generated from the backend's OpenAPI document (`pnpm gen:api` writes openapi.json first).
import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  input: './openapi.json',
  output: { path: 'src/client' },
  plugins: ['@hey-api/client-fetch', '@hey-api/typescript', '@hey-api/sdk'],
})

import { defineConfig } from '@playwright/test'

// The backend in fake mode (scripted model, fixed knowledge base) serves the built SPA on 8743,
// with its own schemas so e2e data never mixes with the app's.
const backend = [
  'cd ../backend',
  // the specs read the zh copy, whatever locale a developer's backend/.env sets
  'export GLASSDESK_LOCALE=zh GLASSDESK_DB_SCHEMA=glassdesk_e2e GLASSDESK_AGENT_SCHEMA=lite_agent_e2e GLASSDESK_STATIC_DIR=../frontend/dist',
  'uv run glassdesk migrate',
  "(printf 'e2e-password\\n' | uv run glassdesk user create e2e-admin --role admin --password-stdin || true)",
  'uv run glassdesk serve --fake --port 8743',
].join(' && ')

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: { baseURL: 'http://127.0.0.1:8743', trace: 'retain-on-failure' },
  webServer: {
    command: backend,
    url: 'http://127.0.0.1:8743/api/health',
    reuseExistingServer: false,
    timeout: 60_000,
  },
})

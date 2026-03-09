/**
 * TuskerSquad API client
 *
 * All calls use RELATIVE paths so Vite's dev-server proxy handles routing:
 *   /api/ui/*  → dashboard BFF (port 8501)
 *   /webhook/* → integration service (port 8001)
 *
 * This works identically in local dev (npm run dev) and inside Docker,
 * because the browser always talks to localhost:5173 and Vite proxies.
 */

async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} ${res.statusText} — ${path}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

const api = {
  // ── Workflow list + detail ──────────────────────────────────────────
  listWorkflows:  ()    => request('/api/ui/workflows'),
  getWorkflow:    (id)  => request(`/api/ui/workflow/${id}`),

  // ── Sub-resources ──────────────────────────────────────────────────
  getAgents:      (id)  => request(`/api/ui/workflow/${id}/agents`),
  getFindings:    (id)  => request(`/api/ui/workflow/${id}/findings`),
  getGovernance:  (id)  => request(`/api/ui/workflow/${id}/governance`),
  getReasoning:   (id)  => request(`/api/ui/workflow/${id}/reasoning`),
  getMergeStatus: (id)  => request(`/api/ui/workflow/${id}/merge-status`),

  getQASummary: async (id) => {
    try { return await request(`/api/ui/workflow/${id}/qa`) }
    catch (e) { if (e.status === 404 || e.status === 502) return null; throw e }
  },

  // ── NEW: LLM conversation log ───────────────────────────────────────
  getLLMLogs:        (id) => request(`/api/ui/workflow/${id}/llm-logs`),

  // ── NEW: Per-agent decision summaries ──────────────────────────────
  getAgentDecisions: (id) => request(`/api/ui/workflow/${id}/agent-decisions`),

  // ── Governance actions ─────────────────────────────────────────────
  approveWorkflow: (id) =>
    request(`/api/ui/workflow/${id}/approve`, { method: 'POST', body: '{}' }),
  rejectWorkflow: (id) =>
    request(`/api/ui/workflow/${id}/reject`, { method: 'POST', body: '{}' }),
  retestWorkflow: (id) =>
    request(`/api/ui/workflow/${id}/retest`, { method: 'POST', body: '{}' }),
  releaseManagerOverride: (id, decision, reason) =>
    request(`/api/ui/workflow/${id}/release`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
    }),

  // ── Trigger workflow via integration service ───────────────────────
  simulateWebhook: (payload) =>
    request('/webhook/simulate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}

export default api

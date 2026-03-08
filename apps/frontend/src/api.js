const DASH_BASE        = import.meta.env.VITE_DASH_URL        || 'http://localhost:8501'
const INTEGRATION_BASE = import.meta.env.VITE_INTEGRATION_URL || 'http://localhost:8001'
const USE_DEMO         = import.meta.env.VITE_USE_DEMO === 'true'

async function request(base, path, options = {}) {
  const res = await fetch(`${base}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status} ${res.statusText} — ${base}${path}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

const api = {
  listWorkflows: () => request(DASH_BASE, '/api/ui/workflows'),

  getWorkflow: (id) => request(DASH_BASE, `/api/ui/workflow/${id}`),

  getAgents: (id) => request(DASH_BASE, `/api/ui/workflow/${id}/agents`),

  getFindings: (id) => request(DASH_BASE, `/api/ui/workflow/${id}/findings`),

  getGovernance: (id) => request(DASH_BASE, `/api/ui/workflow/${id}/governance`),

  getQASummary: async (id) => {
    try {
      return await request(DASH_BASE, `/api/ui/workflow/${id}/qa`)
    } catch (e) {
      if (e.status === 404 || e.status === 502) return null
      throw e
    }
  },

  approveWorkflow: (id) =>
    request(DASH_BASE, `/api/ui/workflow/${id}/approve`, { method: 'POST', body: '{}' }),

  rejectWorkflow: (id) =>
    request(DASH_BASE, `/api/ui/workflow/${id}/reject`, { method: 'POST', body: '{}' }),

  retestWorkflow: (id) =>
    request(DASH_BASE, `/api/ui/workflow/${id}/retest`, { method: 'POST', body: '{}' }),

  releaseManagerOverride: (id, decision, reason) =>
    request(DASH_BASE, `/api/ui/workflow/${id}/release`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
    }),

  simulateWebhook: (payload) =>
    request(INTEGRATION_BASE, '/webhook/simulate', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}

export default api

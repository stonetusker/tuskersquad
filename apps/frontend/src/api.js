const DASH_BASE = import.meta.env.VITE_DASH_URL || 'http://localhost:8501'
const INTEGRATION_BASE = import.meta.env.VITE_INTEGRATION_URL || 'http://localhost:8001'
const USE_DEMO = (import.meta.env.VITE_USE_DEMO === 'true')

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

async function loadDemo() {
  return [
    { workflow_id: 'demo-001', repository: 'tusker/demo-store', pr_number: 42, status: 'WAITING_HUMAN_APPROVAL', created_at: new Date().toISOString() },
    { workflow_id: 'demo-002', repository: 'tusker/auth-service', pr_number: 17, status: 'COMPLETED', created_at: new Date().toISOString() },
  ]
}

const api = {
  listWorkflows: async () => {
    if (USE_DEMO) return loadDemo()
    return request(DASH_BASE, '/api/ui/workflows')
  },

  getWorkflow: async (id) => {
    if (USE_DEMO) return { workflow_id: id, repository: 'tusker/demo', pr_number: 1, status: 'WAITING_HUMAN_APPROVAL' }
    return request(DASH_BASE, `/api/ui/workflow/${id}`)
  },

  getAgents: async (id) => {
    if (USE_DEMO) return []
    return request(DASH_BASE, `/api/ui/workflow/${id}/agents`)
  },

  getFindings: async (id) => {
    if (USE_DEMO) return []
    return request(DASH_BASE, `/api/ui/workflow/${id}/findings`)
  },

  getGovernance: async (id) => {
    if (USE_DEMO) return { actions: [], rationale: null }
    return request(DASH_BASE, `/api/ui/workflow/${id}/governance`)
  },

  // Returns null instead of throwing on 404 (QA summary not ready yet)
  getQASummary: async (id) => {
    if (USE_DEMO) return null
    try {
      return await request(DASH_BASE, `/api/ui/workflow/${id}/qa`)
    } catch (e) {
      if (e.status === 404 || e.status === 502) return null
      throw e
    }
  },

  approveWorkflow: async (id) => {
    return request(DASH_BASE, `/api/ui/workflow/${id}/approve`, { method: 'POST', body: '{}' })
  },

  rejectWorkflow: async (id) => {
    return request(DASH_BASE, `/api/ui/workflow/${id}/reject`, { method: 'POST', body: '{}' })
  },

  retestWorkflow: async (id) => {
    return request(DASH_BASE, `/api/ui/workflow/${id}/retest`, { method: 'POST', body: '{}' })
  },

  releaseManagerOverride: async (id, decision, reason) => {
    return request(DASH_BASE, `/api/ui/workflow/${id}/release`, {
      method: 'POST',
      body: JSON.stringify({ decision, reason }),
    })
  },

  simulateWebhook: async (payload) => {
    return request(INTEGRATION_BASE, '/webhook/simulate', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
}

export default api

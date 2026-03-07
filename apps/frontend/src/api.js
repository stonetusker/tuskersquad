const DASH_BASE = import.meta.env.VITE_DASH_URL || 'http://localhost:8501'
const INTEGRATION_BASE = import.meta.env.VITE_INTEGRATION_URL || 'http://localhost:8001'
const USE_DEMO = (import.meta.env.VITE_USE_DEMO === 'true')

async function loadDemo(){
  try{
    const res = await fetch('/demo_data.json')
    return res.json()
  }catch(e){ return null }
}

async function request(url, opts) {
  const res = await fetch(url, opts)
  if (!res.ok) {
    const txt = await res.text()
    throw new Error(`${res.status} ${res.statusText}: ${txt}`)
  }
  return res.json().catch(() => null)
}

export const api = {
  listWorkflows: async () => {
    if(USE_DEMO){ const d = await loadDemo(); return d?.workflows || [] }
    return request(`${DASH_BASE}/api/ui/workflows`)
  },
  getWorkflow: async (id) => {
    if(USE_DEMO){ const d = await loadDemo(); return (d?.workflows||[]).find(w=>w.workflow_id===id) }
    return request(`${DASH_BASE}/api/ui/workflow/${id}`)
  },
  getAgents: async (id) => {
    if(USE_DEMO){ const d = await loadDemo(); return d?.agents?.[id] || [] }
    return request(`${DASH_BASE}/api/ui/workflow/${id}/agents`)
  },
  getFindings: async (id) => {
    if(USE_DEMO){ const d = await loadDemo(); return d?.findings?.[id] || [] }
    return request(`${DASH_BASE}/api/ui/workflow/${id}/findings`)
  },
  getGovernance: async (id) => {
    if(USE_DEMO){ const d = await loadDemo(); return d?.governance?.[id] || null }
    return request(`${DASH_BASE}/api/ui/workflow/${id}/governance`)
  },
  approveWorkflow: async (id) => {
    if(USE_DEMO){ return {workflow_id:id, status:'COMPLETED'} }
    return request(`${DASH_BASE}/api/ui/workflow/${id}/approve`, {method:'POST'})
  },
  rejectWorkflow: async (id) => {
    if(USE_DEMO){ return {workflow_id:id, status:'REJECTED'} }
    return request(`${DASH_BASE}/api/ui/workflow/${id}/reject`, {method:'POST'})
  },
  simulateWebhook: async (payload) => {
    if(USE_DEMO){
      // Return a synthetic workflow id for demo mode
      const id = `demo-${Date.now()}`
      return {workflow_id:id, status:'RUNNING', repository: payload.repo, pr_number: payload.pr_number, created_at: new Date().toISOString()}
    }
    return request(`${INTEGRATION_BASE}/webhook/simulate`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    })
  }
}

export default api

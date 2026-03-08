import React, { useState } from 'react'
import api from '../api'

export default function ControlPanel({ onStarted }) {
  const [repo,  setRepo]  = useState('tuskeradmin/demo-store')
  const [pr,    setPr]    = useState(42)
  const [busy,  setBusy]  = useState(false)
  const [msg,   setMsg]   = useState(null)  // {text, ok}

  async function start() {
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.simulateWebhook({ repo, pr_number: Number(pr) })
      setMsg({ text: `Workflow started — ${res.workflow_id?.slice(0, 8) || 'ok'}`, ok: true })
      if (onStarted) onStarted(res)
    } catch (e) {
      setMsg({ text: String(e.message || e), ok: false })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel control">
      <h3>🚀 Start Review</h3>

      <div className="form-row">
        <label>Repository</label>
        <input
          value={repo}
          onChange={e => setRepo(e.target.value)}
          placeholder="owner/repo"
        />
      </div>

      <div className="form-row">
        <label>PR Number</label>
        <input
          type="number"
          value={pr}
          onChange={e => setPr(e.target.value)}
          min={1}
        />
      </div>

      <div className="actions">
        <button onClick={start} disabled={busy}>
          {busy ? 'Starting…' : '▶ Start Workflow'}
        </button>
      </div>

      {msg && (
        <div style={{
          marginTop: 8, padding: '6px 10px', borderRadius: 6,
          fontSize: 11,
          background: msg.ok ? '#f0fdf4' : '#fef2f2',
          border: `1px solid ${msg.ok ? '#86efac' : '#fca5a5'}`,
          color: msg.ok ? '#166534' : '#991b1b',
        }}>
          {msg.ok ? '✅' : '❌'} {msg.text}
        </div>
      )}
    </div>
  )
}

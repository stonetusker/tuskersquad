import React, { useState } from 'react'
import api from '../api'

const DEMO_SCENARIOS = [
  { label: '🛒 Normal PR',      repo: 'tuskeradmin/demo-store', pr: 42 },
  { label: '🔐 Security Bug',   repo: 'tuskeradmin/demo-store', pr: 43 },
  { label: '⚡ Latency Issue',  repo: 'tuskeradmin/demo-store', pr: 44 },
  { label: '💰 Pricing Bug',    repo: 'tuskeradmin/demo-store', pr: 45 },
]

export default function ControlPanel({ onStarted }) {
  const [repo,  setRepo]  = useState('tuskeradmin/demo-store')
  const [pr,    setPr]    = useState(42)
  const [busy,  setBusy]  = useState(false)
  const [msg,   setMsg]   = useState(null)

  async function start(r, p) {
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.simulateWebhook({ repo: r || repo, pr_number: Number(p || pr) })
      setMsg({ text: `Review started`, ok: true })
      if (onStarted) onStarted(res)
    } catch (e) {
      setMsg({ text: String(e.message || e), ok: false })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel control-panel">
      <div className="panel-header" style={{ background: '#202123', color: '#FACF0E', borderBottom: '2px solid #FACF0E' }}>
        🚀 Start PR Review
      </div>
      <div className="panel-body">
        <div className="form-row">
          <label>Repository</label>
          <input value={repo} onChange={e => setRepo(e.target.value)} placeholder="owner/repo" />
        </div>
        <div className="form-row">
          <label>PR Number</label>
          <input type="number" value={pr} onChange={e => setPr(e.target.value)} min={1} />
        </div>
        <button className="btn btn-primary" onClick={() => start()} disabled={busy}>
          {busy ? '⏳ Starting…' : '▶ Start Review'}
        </button>

        {msg && (
          <div className={`action-msg ${msg.ok ? 'ok' : 'err'}`} style={{ marginTop: 8 }}>
            {msg.ok ? '✅' : '❌'} {msg.text}
          </div>
        )}

        {/* Quick demo scenarios */}
        <div style={{ marginTop: 14, borderTop: '1px solid #f1f5f9', paddingTop: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#94a3b8', letterSpacing: '0.08em',
                        textTransform: 'uppercase', marginBottom: 6 }}>Quick Demo</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {DEMO_SCENARIOS.map(s => (
              <button
                key={s.label}
                onClick={() => { setRepo(s.repo); setPr(s.pr); start(s.repo, s.pr) }}
                disabled={busy}
                style={{
                  padding: '7px 10px',
                  borderRadius: 6,
                  border: '1px solid #e5e7eb',
                  background: '#fff',
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: busy ? 'not-allowed' : 'pointer',
                  color: busy ? '#94a3b8' : '#374151',
                  textAlign: 'left',
                  fontFamily: 'inherit',
                  transition: 'all 0.1s',
                }}
                onMouseEnter={e => { if (!busy) e.target.style.borderColor = '#FACF0E' }}
                onMouseLeave={e => { e.target.style.borderColor = '#e5e7eb' }}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

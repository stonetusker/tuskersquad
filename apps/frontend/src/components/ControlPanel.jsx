import React, { useState } from 'react'
import api from '../api'

// Quick Demo scenarios — all trigger a review against the running demo-backend.
// To test specific bug scenarios, set the corresponding flag in infra/.env
// and restart: BUG_SECURITY=true, BUG_SLOW=true, BUG_PRICE=true.
// The PR number here is the actual PR you opened in your Gitea shopflow repo.
const DEMO_SCENARIOS = [
  { label: '🛒 Normal PR',      repo: 'tusker/shopflow', pr: 1, hint: 'Standard review, no bugs active' },
  { label: '🔐 Security Bug',   repo: 'tusker/shopflow', pr: 1, hint: 'Set BUG_SECURITY=true in infra/.env first' },
  { label: '⚡ Latency Issue',  repo: 'tusker/shopflow', pr: 1, hint: 'Set BUG_SLOW=true in infra/.env first' },
  { label: '💰 Pricing Bug',    repo: 'tusker/shopflow', pr: 1, hint: 'Set BUG_PRICE=true in infra/.env first' },
]

export default function ControlPanel({ onStarted }) {
  const [repo,  setRepo]  = useState('tusker/shopflow')
  const [pr,    setPr]    = useState(1)
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
                title={s.hint}
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
                onMouseEnter={e => { if (!busy) e.currentTarget.style.borderColor = '#FACF0E' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = '#e5e7eb' }}
              >
                <div>{s.label}</div>
                <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>{s.hint}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

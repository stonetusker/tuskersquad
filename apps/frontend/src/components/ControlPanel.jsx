import React, { useState, useEffect } from 'react'
import api from '../api'

const DEMO_SCENARIOS = [
  { label: '🛒 Normal PR',    hint: 'Standard review, no bugs active' },
  { label: '🔐 Security Bug', hint: 'Set BUG_SECURITY=true in infra/.env first' },
  { label: '⚡ Latency Issue',hint: 'Set BUG_SLOW=true in infra/.env first' },
  { label: '💰 Pricing Bug',  hint: 'Set BUG_PRICE=true in infra/.env first' },
]

export default function ControlPanel({ onStarted }) {
  const [repo,       setRepo]       = useState('')
  const [pr,         setPr]         = useState(1)
  const [busy,       setBusy]       = useState(false)
  const [msg,        setMsg]        = useState(null)
  const [repos,      setRepos]      = useState([])   // available repos from Gitea
  const [gitUser,    setGitUser]    = useState(null)
  const [gitError,   setGitError]   = useState(null)
  const [loadingRepos, setLoadingRepos] = useState(true)

  // Fetch real repos from Gitea on mount
  useEffect(() => {
    api.getGiteaInfo()
      .then(info => {
        if (info.error) {
          setGitError(info.error)
        } else {
          setGitUser(info.user)
          setRepos(info.repos || [])
          if (info.repos && info.repos.length > 0) {
            setRepo(info.repos[0])
          }
        }
      })
      .catch(e => setGitError(String(e.message || e)))
      .finally(() => setLoadingRepos(false))
  }, [])

  async function start(r, p) {
    const repoVal = r || repo
    const prVal   = Number(p || pr)
    if (!repoVal) {
      setMsg({ text: 'Enter a repository (owner/repo)', ok: false })
      return
    }
    setBusy(true)
    setMsg(null)
    try {
      const res = await api.simulateWebhook({ repo: repoVal, pr_number: prVal })
      setMsg({ text: `Review started for ${repoVal} #${prVal}`, ok: true })
      if (onStarted) onStarted(res)
    } catch (e) {
      setMsg({ text: String(e.message || e), ok: false })
    } finally {
      setBusy(false)
    }
  }

  const inputStyle = {
    width: '100%', padding: '7px 10px', border: '1px solid #e5e7eb',
    borderRadius: 6, fontSize: 13, fontFamily: 'inherit', boxSizing: 'border-box',
    outline: 'none',
  }
  const labelStyle = {
    fontSize: 10, fontWeight: 700, color: '#94a3b8',
    letterSpacing: '0.08em', textTransform: 'uppercase',
    display: 'block', marginBottom: 4,
  }

  return (
    <div className="panel control-panel">
      <div className="panel-header"
           style={{ background: '#202123', color: '#FACF0E', borderBottom: '2px solid #FACF0E' }}>
        🚀 Start PR Review
      </div>
      <div className="panel-body">

        {/* Gitea connection status */}
        {loadingRepos ? (
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 8 }}>
            ⏳ Loading Gitea repos…
          </div>
        ) : gitError ? (
          <div style={{ fontSize: 11, color: '#ef4444', background: '#fef2f2',
                        border: '1px solid #fecaca', borderRadius: 6,
                        padding: '6px 8px', marginBottom: 10 }}>
            ⚠️ Gitea not connected — enter repo manually<br/>
            <span style={{ color: '#94a3b8' }}>{gitError}</span>
          </div>
        ) : (
          <div style={{ fontSize: 11, color: '#16a34a', marginBottom: 8 }}>
            ✅ Gitea connected as <strong>{gitUser}</strong> · {repos.length} repo{repos.length !== 1 ? 's' : ''}
          </div>
        )}

        {/* Repository — dropdown if repos available, text input fallback */}
        <div className="form-row" style={{ marginBottom: 10 }}>
          <label style={labelStyle}>Repository</label>
          {repos.length > 0 ? (
            <select
              value={repo}
              onChange={e => setRepo(e.target.value)}
              style={{ ...inputStyle, background: '#fff', cursor: 'pointer' }}
            >
              {repos.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          ) : (
            <input
              value={repo}
              onChange={e => setRepo(e.target.value)}
              placeholder="owner/repo"
              style={inputStyle}
            />
          )}
          {repo && (
            <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 3 }}>
              → {repo}
            </div>
          )}
        </div>

        {/* PR Number */}
        <div className="form-row" style={{ marginBottom: 12 }}>
          <label style={labelStyle}>PR Number</label>
          <input
            type="number"
            value={pr}
            onChange={e => setPr(e.target.value)}
            min={1}
            style={{ ...inputStyle, width: 100 }}
          />
        </div>

        <button className="btn btn-primary" onClick={() => start()} disabled={busy || !repo}>
          {busy ? 'Starting...' : 'Start Review'}
        </button>

        {msg && (
          <div className={`action-msg ${msg.ok ? 'ok' : 'err'}`} style={{ marginTop: 8 }}>
            {msg.ok ? '>' : '!'} {msg.text}
          </div>
        )}

        {/* Quick Demo — uses the currently selected repo */}
        <div style={{ marginTop: 14, borderTop: '1px solid #f1f5f9', paddingTop: 10 }}>
          <div style={labelStyle}>Quick Demo</div>
          {!repo && (
            <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 6 }}>
              Connect Gitea or enter a repo above to enable Quick Demo
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {DEMO_SCENARIOS.map(s => (
              <button
                key={s.label}
                title={s.hint}
                onClick={() => start(repo, pr)}
                disabled={busy || !repo}
                style={{
                  padding: '7px 10px', borderRadius: 6,
                  border: '1px solid #e5e7eb', background: '#fff',
                  fontSize: 12, fontWeight: 500, textAlign: 'left',
                  fontFamily: 'inherit', transition: 'all 0.1s',
                  cursor: (busy || !repo) ? 'not-allowed' : 'pointer',
                  color:  (busy || !repo) ? '#94a3b8' : '#374151',
                  opacity: !repo ? 0.5 : 1,
                }}
                onMouseEnter={e => { if (!busy && repo) e.currentTarget.style.borderColor = '#FACF0E' }}
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

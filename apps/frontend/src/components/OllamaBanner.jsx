import { useEffect, useState } from 'react'
import api from '../api'

// Agents that use LLMs directly — shown in the warning list
const LLM_AGENTS = [
  { name: 'Judge',       model: 'qwen2.5:14b',        role: 'Final Approve / Reject decision' },
  { name: 'QA Lead',     model: 'phi3:mini',           role: 'Risk-level summary' },
  { name: 'Correlator',  model: 'qwen2.5:14b',         role: 'Root cause narrative' },
]

// Required models — checked against the models Ollama reports
const REQUIRED_MODELS = ['qwen2.5:14b', 'deepseek-coder:6.7b', 'phi3:mini']

export default function OllamaBanner() {
  const [status, setStatus] = useState(null)   // null = loading, object once fetched

  useEffect(() => {
    let mounted = true

    async function check() {
      try {
        const s = await api.ollamaStatus()
        if (mounted) setStatus(s)
      } catch {
        if (mounted) setStatus({ available: false, models: [], url: '', error: 'Network error' })
      }
    }

    check()
    // Re-check every 15 s — so banner dismisses automatically when Ollama starts
    const t = setInterval(check, 15000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  // Don't render anything while the first check is in flight
  if (status === null) return null
  // All good — no banner needed
  if (status.available) {
    // Check if all required models are loaded
    const missing = REQUIRED_MODELS.filter(
      m => !status.models.some(loaded => loaded.startsWith(m.split(':')[0]))
    )
    if (missing.length === 0) return null

    // Ollama is up but some models aren't pulled yet
    return (
      <div style={bannerStyle('warning')}>
        <span style={iconStyle}>⚠️</span>
        <div style={bodyStyle}>
          <strong>Ollama is running but some models are not pulled.</strong>
          {' '}LLM-powered agents will fall back to deterministic analysis.
          <br />
          <span style={cmdStyle}>
            ollama pull {missing.join(' && ollama pull ')}
          </span>
          <span style={missingStyle}>Missing: {missing.join(', ')}</span>
        </div>
      </div>
    )
  }

  // Ollama is not reachable
  return (
    <div style={bannerStyle('error')}>
      <span style={iconStyle}>🔴</span>
      <div style={bodyStyle}>
        <strong>Ollama is not reachable at {status.url || 'the configured address'}.</strong>
        {' '}The following agents will run in <em>deterministic-only mode</em> — no LLM reasoning:
        <ul style={listStyle}>
          {LLM_AGENTS.map(a => (
            <li key={a.name} style={listItemStyle}>
              <strong>{a.name}</strong>
              <span style={modelBadge}>{a.model}</span>
              <span style={{ color: '#94a3b8', fontSize: 11 }}> — {a.role}</span>
            </li>
          ))}
        </ul>
        <div style={fixStyle}>
          To fix: start Ollama and set{' '}
          <code style={codeStyle}>OLLAMA_URL</code> in{' '}
          <code style={codeStyle}>infra/.env</code>, then run{' '}
          <code style={codeStyle}>make restart</code>.
        </div>
      </div>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────

const bannerStyle = (type) => ({
  display: 'flex',
  alignItems: 'flex-start',
  gap: 10,
  padding: '10px 14px',
  margin: '0 0 10px 0',
  borderRadius: 6,
  background: type === 'error' ? '#1e1215' : '#1a1700',
  border: `1px solid ${type === 'error' ? '#7f1d1d' : '#713f12'}`,
  fontSize: 12,
  color: type === 'error' ? '#fca5a5' : '#fde68a',
  lineHeight: 1.5,
})

const iconStyle = { fontSize: 16, marginTop: 1, flexShrink: 0 }

const bodyStyle = { flex: 1 }

const listStyle = {
  margin: '6px 0 6px 16px',
  padding: 0,
  listStyle: 'disc',
}

const listItemStyle = { marginBottom: 3 }

const modelBadge = {
  display: 'inline-block',
  background: '#581c87',
  color: '#e9d5ff',
  borderRadius: 3,
  padding: '0 5px',
  fontSize: 10,
  fontWeight: 700,
  marginLeft: 6,
}

const fixStyle = {
  marginTop: 8,
  padding: '6px 10px',
  background: '#0f172a',
  borderRadius: 4,
  color: '#94a3b8',
  fontSize: 11,
}

const codeStyle = {
  background: '#1e293b',
  color: '#38bdf8',
  padding: '1px 4px',
  borderRadius: 3,
  fontFamily: 'monospace',
}

const cmdStyle = {
  display: 'block',
  marginTop: 6,
  padding: '4px 8px',
  background: '#0f172a',
  borderRadius: 4,
  fontFamily: 'monospace',
  color: '#4ade80',
  fontSize: 10,
}

const missingStyle = {
  display: 'block',
  marginTop: 4,
  color: '#fbbf24',
  fontSize: 11,
}

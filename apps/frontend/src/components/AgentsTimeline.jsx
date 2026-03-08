import React from 'react'

const STATUS_COLOR = {
  COMPLETED: '#22c55e',
  RUNNING:   '#3b82f6',
  FAILED:    '#ef4444',
}

const AGENT_ICONS = {
  planner:    '🧭',
  backend:    '⚙️',
  frontend:   '🎨',
  security:   '🔐',
  sre:        '📡',
  challenger: '⚔️',
  qa_lead:    '📋',
  judge:      '⚖️',
}

export default function AgentsTimeline({ agents, currentAgent }) {
  if (!agents || agents.length === 0) {
    if (currentAgent) {
      // Show placeholder when running but no logs yet
      return (
        <div style={{ fontSize: 13, color: '#64748b' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 0',
          }}>
            <span style={{
              width: 8, height: 8, borderRadius: '50%',
              background: '#3b82f6',
              animation: 'ts-pulse 1.2s ease-in-out infinite',
              display: 'inline-block', flexShrink: 0,
            }} />
            <span style={{ fontWeight: 600, color: '#1e293b' }}>
              {AGENT_ICONS[currentAgent] || '🤖'} {currentAgent}
            </span>
            <span style={{ color: '#94a3b8' }}>running…</span>
          </div>
        </div>
      )
    }
    return <div style={{ color: '#94a3b8', fontSize: 13 }}>No agent data yet</div>
  }

  return (
    <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {agents.map((a, idx) => {
        const isActive = a.agent === currentAgent && !a.completed_at
        const color    = isActive ? '#3b82f6' : (STATUS_COLOR[a.status] || '#94a3b8')
        const icon     = AGENT_ICONS[a.agent] || '🤖'

        // Duration
        let duration = ''
        if (a.started_at && a.completed_at) {
          const ms = new Date(a.completed_at) - new Date(a.started_at)
          duration = ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`
        }

        return (
          <li key={idx} style={{
            display: 'flex', gap: 10, alignItems: 'flex-start',
            padding: '7px 0', borderBottom: '1px solid #f1f5f9',
          }}>
            {/* dot / pulse */}
            <div style={{ paddingTop: 4, flexShrink: 0 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%',
                background: color, display: 'inline-block',
                animation: isActive ? 'ts-pulse 1.2s ease-in-out infinite' : 'none',
              }} />
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                display: 'flex', alignItems: 'center',
                gap: 6, flexWrap: 'wrap',
              }}>
                <span style={{ fontSize: 14 }}>{icon}</span>
                <span style={{ fontWeight: 600, fontSize: 13, color: '#1e293b' }}>
                  {a.agent}
                </span>
                <span style={{
                  fontSize: 11, fontWeight: 600,
                  color, letterSpacing: '0.04em',
                }}>
                  {isActive ? 'RUNNING' : (a.status || '')}
                </span>
                {duration && (
                  <span style={{ fontSize: 11, color: '#94a3b8' }}>
                    {duration}
                  </span>
                )}
              </div>

              {a.started_at && (
                <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
                  {new Date(a.started_at).toLocaleTimeString()}
                </div>
              )}

              {a.output && (
                <pre style={{
                  margin: '4px 0 0', fontSize: 10, color: '#64748b',
                  background: '#f8fafc', borderRadius: 4, padding: '4px 6px',
                  whiteSpace: 'pre-wrap', maxHeight: 60, overflowY: 'auto',
                  border: '1px solid #e2e8f0',
                }}>{a.output.slice(0, 200)}</pre>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

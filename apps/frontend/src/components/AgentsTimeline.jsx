import React from 'react'

const AGENT_ICONS = {
  planner: 'PL', backend: 'BE', frontend: 'FE', security: 'SEC',
  sre: 'SRE', challenger: 'CH', qa_lead: 'QA', judge: 'JDG',
}

const STATUS_COLORS = {
  COMPLETED: '#22c55e',
  FAILED:    '#ef4444',
  RUNNING:   '#FACF0E',
}

export default function AgentsTimeline({ agents, currentAgent }) {
  if (!agents || !agents.length) {
    if (currentAgent) {
      return (
        <div className="agent-timeline" style={{ listStyle: 'none' }}>
          <div className="agent-item">
            <div className="agent-dot-col">
              <span className="agent-dot" style={{
                background: '#FACF0E',
                animation: 'ts-pulse 1.2s ease-in-out infinite',
              }} />
            </div>
            <div className="agent-body">
              <div className="agent-name">
                <span className="agent-icon">{AGENT_ICONS[currentAgent] || '??'}</span>
                {currentAgent}
                <span className="badge badge-warn" style={{ fontSize: 9 }}>Running</span>
              </div>
            </div>
          </div>
        </div>
      )
    }
    return <div style={{ color: '#94a3b8', fontSize: 12 }}>No agent data yet</div>
  }

  return (
    <ul className="agent-timeline">
      {agents.map((a, i) => {
        const isActive = a.agent === currentAgent && !a.completed_at
        const color    = isActive ? '#FACF0E' : (STATUS_COLORS[a.status] || '#d1d5db')
        const icon     = AGENT_ICONS[a.agent] || '??'

        let duration = ''
        if (a.started_at && a.completed_at) {
          const ms = new Date(a.completed_at) - new Date(a.started_at)
          duration = ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
        }

        return (
          <li key={i} className="agent-item">
            <div className="agent-dot-col">
              <span className="agent-dot" style={{
                background: color,
                animation: isActive ? 'ts-pulse 1.2s ease-in-out infinite' : 'none',
              }} />
            </div>
            <div className="agent-body">
              <div className="agent-name">
                <span className="agent-icon">{icon}</span>
                {a.agent}
                {isActive && <span className="badge badge-warn" style={{ fontSize: 9 }}>Running</span>}
                {a.status === 'COMPLETED' && <span className="badge badge-ok" style={{ fontSize: 9 }}>Done</span>}
                {a.status === 'FAILED'    && <span className="badge badge-err" style={{ fontSize: 9 }}>Failed</span>}
                {duration && <span className="agent-dur">{duration}</span>}
              </div>
              {a.started_at && (
                <div className="agent-time">{new Date(a.started_at).toLocaleTimeString()}</div>
              )}
              {a.output && (
                <pre className="agent-output">{a.output.slice(0, 200)}</pre>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

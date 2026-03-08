/**
 * RiskHeatmap — Visual grid showing per-agent risk level and finding count
 */
import React from 'react'

const AGENT_META = {
  planner:    { icon: '🧭', label: 'Planner'    },
  backend:    { icon: '⚙️',  label: 'Backend'    },
  frontend:   { icon: '🎨',  label: 'Frontend'   },
  security:   { icon: '🔐',  label: 'Security'   },
  sre:        { icon: '📡',  label: 'SRE'        },
  challenger: { icon: '⚔️',  label: 'Challenger' },
  qa_lead:    { icon: '📋',  label: 'QA Lead'    },
  judge:      { icon: '⚖️',  label: 'Judge'      },
}

const RISK_ORDER = { HIGH: 3, MEDIUM: 2, LOW: 1 }

function getAgentRisk(agentName, findings) {
  const agentFindings = findings.filter(f => f.agent === agentName)
  if (!agentFindings.length) return { risk: 'NONE', count: 0 }
  const maxSev = agentFindings.reduce((best, f) => {
    return (RISK_ORDER[f.severity] || 0) > (RISK_ORDER[best] || 0) ? f.severity : best
  }, 'LOW')
  return { risk: maxSev, count: agentFindings.length }
}

export default function RiskHeatmap({ findings }) {
  if (!findings || !findings.length) {
    return (
      <div style={{ color: '#94a3b8', fontSize: 12, textAlign: 'center', padding: '16px 0' }}>
        No findings data yet
      </div>
    )
  }

  const cells = Object.entries(AGENT_META).map(([id, meta]) => ({
    id,
    ...meta,
    ...getAgentRisk(id, findings),
  }))

  // Sort: HIGH first, then MEDIUM, then LOW, then NONE
  cells.sort((a, b) => (RISK_ORDER[b.risk] || 0) - (RISK_ORDER[a.risk] || 0))

  return (
    <div className="heatmap-grid">
      {cells.map(cell => (
        <div key={cell.id} className={`heatmap-cell risk-${cell.risk}`} title={`${cell.label}: ${cell.count} finding(s)`}>
          <div className="heatmap-agent">{cell.icon}</div>
          <div className="heatmap-label">{cell.label}</div>
          <div className="heatmap-count">{cell.count}</div>
          <div className="heatmap-risk">{cell.risk === 'NONE' ? '—' : cell.risk}</div>
        </div>
      ))}
    </div>
  )
}

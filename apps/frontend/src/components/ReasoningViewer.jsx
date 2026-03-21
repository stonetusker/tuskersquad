/**
 * LLM Reasoning Viewer
 * Displays per-agent LLM output in a dark terminal-style viewer
 * with tab-per-agent switching.
 */
import React, { useState } from 'react'
import { formatClock, fullTooltip } from '../utils/time'

const AGENT_ICONS = {
  planner:'🧭', backend:'⚙️', frontend:'🎨', security:'🔐',
  sre:'📡', challenger:'⚔️', qa_lead:'📋', judge:'⚖️',
}

export default function ReasoningViewer({ reasoning = [] }) {
  const [active, setActive] = useState(0)

  if (!reasoning.length) {
    return (
      <div className="reasoning-viewer" style={{ padding: 16 }}>
        <span style={{ color: '#6B7280', fontSize: 12 }}>
          LLM reasoning will appear here as agents complete…
        </span>
      </div>
    )
  }

  const current = reasoning[active] || reasoning[0]

  return (
    <div className="reasoning-viewer">
      {/* Agent tabs */}
      <div className="reasoning-tabs">
        {reasoning.map((r, i) => (
          <button
            key={i}
            className={`reasoning-tab ${i === active ? 'active' : ''}`}
            onClick={() => setActive(i)}
          >
            {AGENT_ICONS[r.agent] || '??'} {r.agent}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="reasoning-body">
        {current && (
          <>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginBottom: 10, fontSize: 10, color: '#6B7280',
            }}>
              <span>
                {current.started_at && <span title={fullTooltip(current.started_at)}>Started: {formatClock(current.started_at)}</span>}
              </span>
              <span>
                {current.completed_at && <span title={fullTooltip(current.completed_at)}>Completed: {formatClock(current.completed_at)}</span>}
              </span>
            </div>
            <pre>{current.output || '(no output recorded)'}</pre>
          </>
        )}
      </div>
    </div>
  )
}

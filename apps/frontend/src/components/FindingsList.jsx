import React, { useState } from 'react'

const SEV_LABEL = { HIGH: 'HIGH', MEDIUM: 'MED', LOW: 'LOW' }

export default function FindingsList({ findings }) {
  const [filter, setFilter] = useState('ALL')
  const [expanded, setExpanded] = useState({})

  if (!findings || !findings.length) {
    return <div style={{ color: '#94a3b8', fontSize: 12, padding: '8px 0' }}>No findings yet</div>
  }

  const filtered = filter === 'ALL' ? findings : findings.filter(f => f.severity === filter)
  const counts = { HIGH: 0, MEDIUM: 0, LOW: 0 }
  findings.forEach(f => { if (counts[f.severity] !== undefined) counts[f.severity]++ })

  return (
    <div>
      {/* Filter pills */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 8, flexWrap: 'wrap' }}>
        {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map(s => {
          const active = filter === s
          const colors = { HIGH: '#fee2e2', MEDIUM: '#fef3c7', LOW: '#dcfce7', ALL: '#f3f4f6' }
          const borders = { HIGH: '#fca5a5', MEDIUM: '#fcd34d', LOW: '#86efac', ALL: '#d1d5db' }
          return (
            <button
              key={s}
              onClick={() => setFilter(s)}
              style={{
                padding: '3px 9px',
                borderRadius: 20,
                border: `1.5px solid ${active ? borders[s] : '#e5e7eb'}`,
                background: active ? colors[s] : '#fff',
                fontSize: 10,
                fontWeight: 700,
                cursor: 'pointer',
                color: active ? '#374151' : '#9ca3af',
                transition: 'all 0.1s',
                fontFamily: 'inherit',
              }}
            >
              {s}{s !== 'ALL' ? ` (${counts[s]})` : ` (${findings.length})`}
            </button>
          )
        })}
      </div>

      <ul className="findings-list">
        {filtered.map(f => {
          const isOpen = expanded[f.id]
          const sevColor = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#22c55e' }[f.severity] || '#94a3b8'
          return (
            <li
              key={f.id}
              className="finding-item"
              onClick={() => setExpanded(e => ({ ...e, [f.id]: !e[f.id] }))}
              style={{ cursor: 'pointer' }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div className="finding-title" style={{ paddingRight: 8 }}>{f.title}</div>
                <span style={{
                  fontSize: 9, fontWeight: 800, padding: '2px 6px', borderRadius: 3,
                  background: { HIGH: '#fee2e2', MEDIUM: '#fef3c7', LOW: '#dcfce7' }[f.severity] || '#f3f4f6',
                  color: sevColor, letterSpacing: '0.06em', flexShrink: 0,
                }}>
                  {SEV_LABEL[f.severity] || f.severity}
                </span>
              </div>
              <div className="finding-meta">
                <span className={`sev-dot sev-${f.severity}`} />
                <span>{f.agent}</span>
                {f.created_at && (
                  <span style={{ marginLeft: 'auto', color: '#d1d5db' }}>
                    {new Date(f.created_at).toLocaleTimeString()}
                  </span>
                )}
              </div>
              {isOpen && f.description && (
                <div className="finding-desc">{f.description}</div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

import React, { useEffect, useState } from 'react'
import api from '../api'

const STATUS_CFG = {
  COMPLETED:              { color: '#22c55e', label: 'Done'     },
  WAITING_HUMAN_APPROVAL: { color: '#FACF0E', label: 'Awaiting' },
  RUNNING:                { color: '#3b82f6', label: 'Running'  },
  FAILED:                 { color: '#ef4444', label: 'Failed'   },
}

export default function WorkflowList({ onSelect, selectedId }) {
  const [list,    setList]    = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let mounted = true
    async function load() {
      if (!loading) setLoading(true)
      try {
        const data = await api.listWorkflows()
        if (mounted) setList(data || [])
      } catch (e) {
        console.error(e)
      } finally {
        if (mounted) setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 4000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  return (
    <div className="panel">
      <div className="panel-header">
        🗂 Recent Reviews
        {loading && <span style={{ fontSize: 9, opacity: 0.5, marginLeft: 4 }}>●</span>}
      </div>
      <div style={{ padding: '8px 10px' }}>
        {list.length === 0 && !loading && (
          <div style={{ color: '#94a3b8', fontSize: 12, textAlign: 'center', padding: '16px 0' }}>
            No reviews yet — start one above
          </div>
        )}
        <ul className="wf-list">
          {list.map(w => {
            const cfg = STATUS_CFG[w.status] || { color: '#94a3b8', label: w.status }
            const isRunning = w.status === 'RUNNING'
            return (
              <li
                key={w.workflow_id}
                className={`wf-item ${w.workflow_id === selectedId ? 'selected' : ''}`}
                onClick={() => onSelect?.(w.workflow_id)}
              >
                <div className="wf-repo">
                  {w.repository}
                  <span className="wf-pr-num">#{w.pr_number}</span>
                </div>
                <div className="wf-meta">
                  <span
                    className="mini-dot"
                    style={{
                      background: cfg.color,
                      animation: isRunning ? 'ts-pulse 1.4s ease-in-out infinite' : 'none',
                    }}
                  />
                  <span style={{ color: cfg.color, fontWeight: 700, fontSize: 10 }}>{cfg.label}</span>
                  {w.merge_status === 'success' && (
                    <span style={{ fontSize: 9, color: '#22c55e', fontWeight: 600 }}>🔀 merged</span>
                  )}
                  {w.deploy_status === 'triggered' && (
                    <span style={{ fontSize: 9, color: '#3b82f6', fontWeight: 600 }}>deployed</span>
                  )}
                  <span style={{ color: '#d1d5db', marginLeft: 'auto', fontSize: 10 }}>
                    {w.created_at ? new Date(w.created_at).toLocaleTimeString() : ''}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

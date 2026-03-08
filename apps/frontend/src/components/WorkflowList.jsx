import React, { useEffect, useState } from 'react'
import api from '../api'

const STATUS_COLOR = {
  COMPLETED:              '#22c55e',
  WAITING_HUMAN_APPROVAL: '#f59e0b',
  RUNNING:                '#3b82f6',
  FAILED:                 '#ef4444',
}

const STATUS_LABEL = {
  COMPLETED:              'Done',
  WAITING_HUMAN_APPROVAL: 'Awaiting',
  RUNNING:                'Running',
  FAILED:                 'Failed',
}

function MiniDot({ color, pulse }) {
  return (
    <span style={{
      width: 7, height: 7, borderRadius: '50%',
      background: color, display: 'inline-block', flexShrink: 0,
      animation: pulse ? 'ts-pulse 1.4s ease-in-out infinite' : 'none',
    }} />
  )
}

export default function WorkflowList({ onSelect, selectedId }) {
  const [list,    setList]    = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let mounted = true
    async function load() {
      setLoading(true)
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
    <div className="panel workflows">
      <h3>
        🗂 Workflows
        {loading && (
          <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 6,
                         fontWeight: 400 }}>syncing…</span>
        )}
      </h3>

      <ul className="workflow-list">
        {list.map(w => {
          const isRunning = w.status === 'RUNNING'
          const color     = STATUS_COLOR[w.status] || '#94a3b8'
          const label     = STATUS_LABEL[w.status] || w.status

          return (
            <li
              key={w.workflow_id}
              className={w.workflow_id === selectedId ? 'selected' : ''}
              onClick={() => onSelect && onSelect(w.workflow_id)}
            >
              <div className="wf-title">
                {w.repository}
                <span style={{ color: '#00b4d8', fontWeight: 500 }}>
                  {' '}#{w.pr_number}
                </span>
              </div>
              <div className="wf-meta">
                <MiniDot color={color} pulse={isRunning} />
                <span style={{ color, fontWeight: 600, fontSize: 10 }}>{label}</span>
                {w.merge_status === 'success' && (
                  <span style={{ fontSize: 10, color: '#22c55e' }}>🔀 merged</span>
                )}
                {w.deploy_status === 'triggered' && (
                  <span style={{ fontSize: 10, color: '#3b82f6' }}>🚀 deployed</span>
                )}
                <span style={{ color: '#cbd5e1' }}>
                  {w.created_at ? new Date(w.created_at).toLocaleTimeString() : ''}
                </span>
              </div>
            </li>
          )
        })}
      </ul>

      {list.length === 0 && !loading && (
        <div className="muted" style={{ padding: '12px 0', textAlign: 'center' }}>
          No workflows yet — start one above.
        </div>
      )}
    </div>
  )
}

import React, { useEffect, useState } from 'react'
import api from '../api'
import FindingsList from './FindingsList'
import AgentsTimeline from './AgentsTimeline'

const SEVERITY_COLOR = { HIGH: '#e74c3c', MEDIUM: '#f39c12', LOW: '#27ae60' }

function RiskBadge({ level }) {
  const color = SEVERITY_COLOR[level] || '#95a5a6'
  return (
    <span style={{
      background: color, color: '#fff', borderRadius: 4,
      padding: '2px 10px', fontWeight: 700, fontSize: 13,
    }}>{level || 'UNKNOWN'}</span>
  )
}

export default function WorkflowDetail({ workflowId }) {
  const [detail, setDetail] = useState(null)
  const [agents, setAgents] = useState([])
  const [findings, setFindings] = useState([])
  const [gov, setGov] = useState(null)
  const [qa, setQa] = useState(null)
  const [busy, setBusy] = useState(false)
  const [releaseReason, setReleaseReason] = useState('')
  const [showRelease, setShowRelease] = useState(false)
  const [actionMsg, setActionMsg] = useState('')

  useEffect(() => {
    if (!workflowId) return
    let mounted = true

    async function load() {
      try {
        const [d, a, f, g, q] = await Promise.all([
          api.getWorkflow(workflowId),
          api.getAgents(workflowId).catch(() => []),
          api.getFindings(workflowId).catch(() => []),
          api.getGovernance(workflowId).catch(() => ({ actions: [], rationale: null })),
          api.getQASummary(workflowId).catch(() => null),
        ])
        if (mounted) {
          setDetail(d)
          setAgents(a || [])
          setFindings(f || [])
          setGov(g)
          setQa(q)
        }
      } catch (e) { console.error('WorkflowDetail load error:', e) }
    }

    load()
    const t = setInterval(load, 4000)
    return () => { mounted = false; clearInterval(t) }
  }, [workflowId])

  async function doAction(fn, label) {
    setBusy(true)
    setActionMsg('')
    try {
      const res = await fn()
      setActionMsg(`${label}: ${res?.status || 'done'}`)
      setDetail(d => d ? { ...d, status: res?.status || d.status } : d)
    } catch (e) {
      setActionMsg(`Error: ${e.message}`)
    }
    setBusy(false)
  }

  if (!detail) return <div className="panel">Loading workflow...</div>

  const isWaiting = detail.status === 'WAITING_HUMAN_APPROVAL'
  const rationale = detail?.rationale || gov?.rationale

  return (
    <div className="panel detail">
      <div className="wf-header">
        <div>
          <div className="wf-id">{detail.workflow_id?.slice(0, 8)}…</div>
          <div style={{ fontSize: 13, color: '#888' }}>
            {detail.repository}#{detail.pr_number}
          </div>
        </div>
        <div className="wf-status" style={{
          background: detail.status === 'COMPLETED' ? '#27ae60'
            : detail.status === 'WAITING_HUMAN_APPROVAL' ? '#f39c12'
            : detail.status === 'RUNNING' ? '#3498db' : '#e74c3c',
          color: '#fff', borderRadius: 4, padding: '4px 12px', fontWeight: 700,
        }}>
          {detail.status}
        </div>
      </div>

      <div className="wf-grid">
        {/* Agents column */}
        <div className="wf-col">
          <h4>Agent Timeline</h4>
          <AgentsTimeline agents={agents} />
        </div>

        {/* Findings column */}
        <div className="wf-col">
          <h4>Findings ({findings.length})</h4>
          <FindingsList findings={findings} />
        </div>

        {/* QA Summary column */}
        <div className="wf-col">
          <h4>QA Lead Summary</h4>
          {qa ? (
            <div className="qa-summary">
              <div style={{ marginBottom: 8 }}>
                Risk Level: <RiskBadge level={qa.risk_level} />
              </div>
              <pre style={{
                whiteSpace: 'pre-wrap', fontSize: 12,
                background: '#f8f8f8', padding: 10, borderRadius: 4,
                maxHeight: 240, overflowY: 'auto',
              }}>{qa.summary}</pre>
            </div>
          ) : (
            <div className="muted">QA summary not yet available</div>
          )}

          {rationale && (
            <div style={{ marginTop: 16 }}>
              <h5 style={{ margin: '0 0 6px' }}>Judge Rationale</h5>
              <pre style={{
                whiteSpace: 'pre-wrap', fontSize: 12,
                background: '#f0f4ff', padding: 10, borderRadius: 4,
                maxHeight: 160, overflowY: 'auto',
              }}>{rationale}</pre>
            </div>
          )}
        </div>
      </div>

      {/* Human Governance Actions */}
      <div className="wf-actions" style={{ marginTop: 20 }}>
        <div style={{ marginBottom: 8, fontWeight: 600 }}>
          Human Governance {isWaiting && <span style={{ color: '#f39c12' }}> — Awaiting Decision</span>}
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            onClick={() => doAction(() => api.approveWorkflow(workflowId), 'Approved')}
            disabled={busy}
            style={{ background: '#27ae60', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 20px', cursor: 'pointer', fontWeight: 600 }}
          >
            ✓ Approve
          </button>
          <button
            onClick={() => doAction(() => api.rejectWorkflow(workflowId), 'Rejected')}
            disabled={busy}
            style={{ background: '#e74c3c', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 20px', cursor: 'pointer', fontWeight: 600 }}
          >
            ✗ Reject
          </button>
          <button
            onClick={() => doAction(() => api.retestWorkflow(workflowId), 'Retest requested')}
            disabled={busy}
            style={{ background: '#3498db', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 20px', cursor: 'pointer', fontWeight: 600 }}
          >
            ↺ Retest
          </button>
          <button
            onClick={() => setShowRelease(v => !v)}
            disabled={busy}
            style={{ background: '#8e44ad', color: '#fff', border: 'none', borderRadius: 4, padding: '8px 20px', cursor: 'pointer', fontWeight: 600 }}
          >
            ⚡ Release Override
          </button>
        </div>

        {/* Release Manager Panel */}
        {showRelease && (
          <div style={{
            marginTop: 14, background: '#f5eeff', border: '1px solid #c39bd3',
            borderRadius: 6, padding: 14,
          }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Release Manager Override</div>
            <div style={{ fontSize: 12, color: '#666', marginBottom: 10 }}>
              This overrides the QA Lead decision. A business justification is required.
            </div>
            <input
              placeholder="Business justification reason..."
              value={releaseReason}
              onChange={e => setReleaseReason(e.target.value)}
              style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #ccc', marginBottom: 10, boxSizing: 'border-box' }}
            />
            <div style={{ display: 'flex', gap: 10 }}>
              <button
                onClick={() => doAction(() => api.releaseManagerOverride(workflowId, 'APPROVE', releaseReason || 'Release Manager override'), 'Release approved')}
                disabled={busy}
                style={{ background: '#27ae60', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 16px', cursor: 'pointer' }}
              >
                Force Approve
              </button>
              <button
                onClick={() => doAction(() => api.releaseManagerOverride(workflowId, 'REJECT', releaseReason || 'Release Manager override'), 'Release rejected')}
                disabled={busy}
                style={{ background: '#e74c3c', color: '#fff', border: 'none', borderRadius: 4, padding: '6px 16px', cursor: 'pointer' }}
              >
                Force Reject
              </button>
            </div>
          </div>
        )}

        {actionMsg && (
          <div style={{
            marginTop: 10, padding: '8px 14px',
            background: actionMsg.startsWith('Error') ? '#fdecea' : '#eafbea',
            borderRadius: 4, fontSize: 13,
          }}>
            {actionMsg}
          </div>
        )}
      </div>

      {/* Governance history */}
      {gov?.actions && gov.actions.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h4 style={{ margin: '0 0 8px' }}>Governance History</h4>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#f0f0f0' }}>
                <th style={{ padding: '6px 10px', textAlign: 'left' }}>Decision</th>
                <th style={{ padding: '6px 10px', textAlign: 'left' }}>Approved</th>
                <th style={{ padding: '6px 10px', textAlign: 'left' }}>Time</th>
              </tr>
            </thead>
            <tbody>
              {gov.actions.map((a, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                  <td style={{ padding: '5px 10px' }}>{a.decision}</td>
                  <td style={{ padding: '5px 10px' }}>
                    {a.approved === true ? '✓' : a.approved === false ? '✗' : '—'}
                  </td>
                  <td style={{ padding: '5px 10px', color: '#888' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleTimeString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

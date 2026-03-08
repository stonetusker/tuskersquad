import React, { useEffect, useState, useCallback } from 'react'
import api from '../api'
import FindingsList from './FindingsList'
import AgentsTimeline from './AgentsTimeline'

// ─── constants ───────────────────────────────────────────────────────────────
const SEV_COLOR  = { HIGH: '#ef4444', MEDIUM: '#f59e0b', LOW: '#22c55e' }
const STATUS_CFG = {
  COMPLETED:              { bg: '#22c55e', label: 'Completed'              },
  WAITING_HUMAN_APPROVAL: { bg: '#f59e0b', label: 'Awaiting Decision'       },
  RUNNING:                { bg: '#3b82f6', label: 'Running'                 },
  FAILED:                 { bg: '#ef4444', label: 'Failed'                  },
  DEFAULT:                { bg: '#64748b', label: 'Unknown'                 },
}
const MERGE_CFG  = {
  pending:  { icon: '⏳', color: '#f59e0b', label: 'Merging…'      },
  success:  { icon: '🔀', color: '#22c55e', label: 'Merged'         },
  failed:   { icon: '❌', color: '#ef4444', label: 'Merge failed'   },
  skipped:  { icon: '—',  color: '#94a3b8', label: 'Merge skipped'  },
}
const DEPLOY_CFG = {
  pending:   { icon: '⏳', color: '#f59e0b', label: 'Deploying…'       },
  triggered: { icon: '🚀', color: '#22c55e', label: 'Deploy triggered' },
  failed:    { icon: '❌', color: '#ef4444', label: 'Deploy failed'    },
  skipped:   { icon: '—',  color: '#94a3b8', label: 'Deploy skipped'  },
}

// ─── tiny components ─────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || STATUS_CFG.DEFAULT
  const pulse = status === 'RUNNING'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: cfg.bg, color: '#fff',
      borderRadius: 6, padding: '4px 14px',
      fontWeight: 700, fontSize: 13, letterSpacing: '0.03em',
    }}>
      {pulse && (
        <span style={{
          width: 8, height: 8, borderRadius: '50%',
          background: '#fff', opacity: 0.85,
          animation: 'ts-pulse 1.4s ease-in-out infinite',
          display: 'inline-block',
        }} />
      )}
      {cfg.label}
    </span>
  )
}

function RiskBadge({ level }) {
  const color = SEV_COLOR[level] || '#94a3b8'
  return (
    <span style={{
      background: color, color: '#fff',
      borderRadius: 4, padding: '2px 10px',
      fontWeight: 700, fontSize: 12,
    }}>{level || 'UNKNOWN'}</span>
  )
}

function MergeDeployBanner({ mergeStatus, deployStatus, deployUrl }) {
  if (!mergeStatus && !deployStatus) return null

  const mc = MERGE_CFG[mergeStatus]
  const dc = DEPLOY_CFG[deployStatus]

  return (
    <div style={{
      display: 'flex', gap: 10, flexWrap: 'wrap',
      padding: '10px 14px',
      background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
      borderRadius: 8, border: '1px solid #334155',
      marginBottom: 4,
    }}>
      {mc && (
        <span style={{
          display: 'flex', alignItems: 'center', gap: 6,
          color: mc.color, fontWeight: 600, fontSize: 13,
        }}>
          {mc.icon} <span>{mc.label}</span>
        </span>
      )}

      {mc && dc && (
        <span style={{ color: '#475569', fontSize: 13 }}>·</span>
      )}

      {dc && (
        <span style={{
          display: 'flex', alignItems: 'center', gap: 6,
          color: dc.color, fontWeight: 600, fontSize: 13,
        }}>
          {dc.icon}
          {deployUrl && deployStatus === 'triggered' ? (
            <a href={deployUrl} target="_blank" rel="noreferrer"
               style={{ color: dc.color, textDecoration: 'none' }}>
              {dc.label} ↗
            </a>
          ) : (
            <span>{dc.label}</span>
          )}
        </span>
      )}
    </div>
  )
}

function ActionBtn({ onClick, disabled, color, children, title }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        background: color, color: '#fff',
        border: 'none', borderRadius: 6,
        padding: '9px 18px', cursor: disabled ? 'not-allowed' : 'pointer',
        fontWeight: 600, fontSize: 13,
        opacity: disabled ? 0.55 : 1,
        transition: 'opacity 0.15s, transform 0.1s',
        display: 'flex', alignItems: 'center', gap: 6,
      }}
    >
      {children}
    </button>
  )
}

function SectionCard({ title, icon, children }) {
  return (
    <div style={{
      background: '#fff', borderRadius: 8, border: '1px solid #e2e8f0',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: '1px solid #e2e8f0',
        background: '#f8fafc',
        display: 'flex', alignItems: 'center', gap: 8,
        fontWeight: 700, fontSize: 13, color: '#1e293b',
      }}>
        {icon && <span>{icon}</span>}
        {title}
      </div>
      <div style={{ padding: 14 }}>{children}</div>
    </div>
  )
}

// ─── main component ───────────────────────────────────────────────────────────
export default function WorkflowDetail({ workflowId }) {
  const [detail,        setDetail]        = useState(null)
  const [agents,        setAgents]        = useState([])
  const [findings,      setFindings]      = useState([])
  const [gov,           setGov]           = useState(null)
  const [qa,            setQa]            = useState(null)
  const [mergeStatus,   setMergeStatus]   = useState(null)
  const [deployStatus,  setDeployStatus]  = useState(null)
  const [deployUrl,     setDeployUrl]     = useState('')
  const [busy,          setBusy]          = useState(false)
  const [releaseReason, setReleaseReason] = useState('')
  const [showRelease,   setShowRelease]   = useState(false)
  const [actionMsg,     setActionMsg]     = useState(null)   // {text, ok}

  const isWaiting  = detail?.status === 'WAITING_HUMAN_APPROVAL'
  const isRunning  = detail?.status === 'RUNNING'
  const isDone     = detail?.status === 'COMPLETED'
  const isMerging  = mergeStatus === 'pending'
  const isDeploying= deployStatus === 'pending'
  const anyBusy    = busy || isMerging || isDeploying

  // ── load all data ─────────────────────────────────────────────────────────
  const load = useCallback(async () => {
    if (!workflowId) return
    try {
      const [d, a, f, g, q] = await Promise.all([
        api.getWorkflow(workflowId),
        api.getAgents(workflowId).catch(() => []),
        api.getFindings(workflowId).catch(() => []),
        api.getGovernance(workflowId).catch(() => ({ actions: [], rationale: null })),
        api.getQASummary(workflowId).catch(() => null),
      ])
      setDetail(d)
      setAgents(a  || [])
      setFindings(f || [])
      setGov(g)
      setQa(q)
      // Seed merge/deploy from workflow detail
      if (d?.merge_status  !== undefined) setMergeStatus(d.merge_status)
      if (d?.deploy_status !== undefined) setDeployStatus(d.deploy_status)
      if (d?.deploy_url)                  setDeployUrl(d.deploy_url)
    } catch (e) {
      console.error('WorkflowDetail load error:', e)
    }
  }, [workflowId])

  // ── poll merge/deploy status separately (lightweight) ─────────────────────
  const pollMergeDeploy = useCallback(async () => {
    if (!workflowId) return
    try {
      const r = await fetch(
        `${import.meta.env.VITE_DASH_URL || 'http://localhost:8501'}/api/ui/workflow/${workflowId}/merge-status`
      )
      if (r.ok) {
        const d = await r.json()
        setMergeStatus(d.merge_status)
        setDeployStatus(d.deploy_status)
        if (d.deploy_url) setDeployUrl(d.deploy_url)
      }
    } catch (_) {}
  }, [workflowId])

  useEffect(() => {
    if (!workflowId) return
    load()
    const t1 = setInterval(load, 4000)
    return () => clearInterval(t1)
  }, [workflowId, load])

  // Extra fast poll only while merging/deploying
  useEffect(() => {
    if (!isMerging && !isDeploying) return
    const t2 = setInterval(pollMergeDeploy, 1500)
    return () => clearInterval(t2)
  }, [isMerging, isDeploying, pollMergeDeploy])

  // ── action handler ────────────────────────────────────────────────────────
  async function doAction(fn, label) {
    setBusy(true)
    setActionMsg(null)
    try {
      const res = await fn()
      setActionMsg({ text: `${label} — ${res?.status || 'done'}`, ok: true })
      if (res?.status) setDetail(d => d ? { ...d, status: res.status } : d)
      // If auto-merge queued, start polling immediately
      if (res?.auto_merge_queued) {
        setMergeStatus('pending')
        setTimeout(pollMergeDeploy, 800)
      }
      if (res?.deploy_queued) {
        setDeployStatus('pending')
      }
    } catch (e) {
      setActionMsg({ text: `Error: ${e.message}`, ok: false })
    }
    setBusy(false)
  }

  if (!detail) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: 200, color: '#94a3b8', fontSize: 14,
      }}>
        Loading workflow…
      </div>
    )
  }

  const rationale = detail?.rationale || gov?.rationale

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div style={{
        background: 'linear-gradient(135deg, #0b1220 0%, #1e293b 100%)',
        borderRadius: 10, padding: '14px 18px',
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        boxShadow: '0 2px 8px rgba(0,0,0,0.18)',
      }}>
        <div>
          <div style={{
            fontFamily: 'monospace', fontSize: 12,
            color: '#00b4d8', letterSpacing: '0.08em', marginBottom: 4,
          }}>
            #{detail.workflow_id?.slice(0, 8)}
          </div>
          <div style={{ fontWeight: 700, fontSize: 16, color: '#f1f5f9' }}>
            {detail.repository}
            <span style={{ color: '#00b4d8', marginLeft: 4 }}>
              PR #{detail.pr_number}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            {detail.created_at
              ? new Date(detail.created_at).toLocaleString()
              : ''}
          </div>
        </div>
        <StatusBadge status={detail.status} />
      </div>

      {/* ── Merge / Deploy Banner ───────────────────────────────────────────── */}
      <MergeDeployBanner
        mergeStatus={mergeStatus}
        deployStatus={deployStatus}
        deployUrl={deployUrl}
      />

      {/* ── Agent · Findings · QA  grid ────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 220px', minWidth: 0 }}>
          <SectionCard title="Agent Timeline" icon="🤖">
            <AgentsTimeline agents={agents} currentAgent={detail.current_agent} />
          </SectionCard>
        </div>
        <div style={{ flex: '1 1 220px', minWidth: 0 }}>
          <SectionCard title={`Findings (${findings.length})`} icon="🔍">
            <FindingsList findings={findings} />
          </SectionCard>
        </div>
        <div style={{ flex: '1 1 220px', minWidth: 0 }}>
          <SectionCard title="QA Lead Summary" icon="📋">
            {qa ? (
              <>
                <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 12, color: '#64748b' }}>Risk:</span>
                  <RiskBadge level={qa.risk_level} />
                </div>
                <pre style={{
                  whiteSpace: 'pre-wrap', fontSize: 11, lineHeight: 1.6,
                  background: '#f8fafc', borderRadius: 6, padding: 10,
                  maxHeight: 220, overflowY: 'auto', margin: 0,
                  border: '1px solid #e2e8f0', color: '#374151',
                }}>{qa.summary}</pre>
              </>
            ) : (
              <div style={{ color: '#94a3b8', fontSize: 13, padding: '8px 0' }}>
                {isRunning ? 'QA summary generating…' : 'No QA summary yet'}
              </div>
            )}

            {rationale && (
              <div style={{ marginTop: 12 }}>
                <div style={{ fontWeight: 600, fontSize: 12, color: '#475569', marginBottom: 6 }}>
                  ⚖️ Judge Rationale
                </div>
                <pre style={{
                  whiteSpace: 'pre-wrap', fontSize: 11, lineHeight: 1.6,
                  background: '#eff6ff', borderRadius: 6, padding: 10,
                  maxHeight: 140, overflowY: 'auto', margin: 0,
                  border: '1px solid #bfdbfe', color: '#1e3a5f',
                }}>{rationale}</pre>
              </div>
            )}
          </SectionCard>
        </div>
      </div>

      {/* ── Governance Actions ──────────────────────────────────────────────── */}
      <div style={{
        background: '#fff', borderRadius: 8,
        border: isWaiting ? '2px solid #f59e0b' : '1px solid #e2e8f0',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '10px 16px',
          background: isWaiting
            ? 'linear-gradient(90deg, #fffbeb, #fef3c7)'
            : '#f8fafc',
          borderBottom: '1px solid #e2e8f0',
          display: 'flex', alignItems: 'center', gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>
            {isWaiting ? '⏸️' : isDone ? '✅' : '⚙️'}
          </span>
          <span style={{ fontWeight: 700, fontSize: 14, color: '#1e293b' }}>
            Human Governance
          </span>
          {isWaiting && (
            <span style={{
              background: '#f59e0b', color: '#fff',
              borderRadius: 4, padding: '2px 8px',
              fontSize: 11, fontWeight: 700, letterSpacing: '0.05em',
            }}>AWAITING DECISION</span>
          )}
        </div>

        <div style={{ padding: '14px 16px' }}>
          {/* Buttons row */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
            <ActionBtn
              onClick={() => doAction(() => api.approveWorkflow(workflowId), 'Approved')}
              disabled={anyBusy}
              color="#16a34a"
              title="Approve this PR — triggers auto-merge if enabled"
            >
              ✓ Approve
            </ActionBtn>
            <ActionBtn
              onClick={() => doAction(() => api.rejectWorkflow(workflowId), 'Rejected')}
              disabled={anyBusy}
              color="#dc2626"
              title="Reject this PR"
            >
              ✗ Reject
            </ActionBtn>
            <ActionBtn
              onClick={() => doAction(() => api.retestWorkflow(workflowId), 'Retest queued')}
              disabled={anyBusy}
              color="#2563eb"
              title="Re-run all agents"
            >
              ↺ Retest
            </ActionBtn>
            <ActionBtn
              onClick={() => setShowRelease(v => !v)}
              disabled={anyBusy}
              color="#7c3aed"
              title="Override with Release Manager authority"
            >
              ⚡ Release Override
            </ActionBtn>
          </div>

          {/* Auto-merge hint */}
          {isWaiting && (
            <div style={{
              fontSize: 12, color: '#475569',
              background: '#f1f5f9', borderRadius: 6,
              padding: '8px 12px', marginBottom: 12,
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              <span>🔀</span>
              <span>
                <strong>Approve</strong> will automatically merge this PR
                {' '}and trigger the deploy pipeline if configured.
              </span>
            </div>
          )}

          {/* Release Manager panel */}
          {showRelease && (
            <div style={{
              background: '#faf5ff', border: '1px solid #c4b5fd',
              borderRadius: 8, padding: 14, marginBottom: 12,
            }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: '#5b21b6', marginBottom: 6 }}>
                ⚡ Release Manager Override
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 10 }}>
                Overrides AI governance. A written business justification is required and
                will be posted to the PR.
              </div>
              <input
                placeholder="Business justification (required)…"
                value={releaseReason}
                onChange={e => setReleaseReason(e.target.value)}
                style={{
                  width: '100%', padding: '8px 10px', borderRadius: 6,
                  border: '1px solid #c4b5fd', marginBottom: 10,
                  fontSize: 13, boxSizing: 'border-box',
                  outline: 'none',
                }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <ActionBtn
                  onClick={() => doAction(
                    () => api.releaseManagerOverride(workflowId, 'APPROVE', releaseReason || 'Release Manager override'),
                    'Force approved'
                  )}
                  disabled={anyBusy}
                  color="#16a34a"
                >
                  Force Approve
                </ActionBtn>
                <ActionBtn
                  onClick={() => doAction(
                    () => api.releaseManagerOverride(workflowId, 'REJECT', releaseReason || 'Release Manager override'),
                    'Force rejected'
                  )}
                  disabled={anyBusy}
                  color="#dc2626"
                >
                  Force Reject
                </ActionBtn>
              </div>
            </div>
          )}

          {/* Action result message */}
          {actionMsg && (
            <div style={{
              padding: '8px 14px', borderRadius: 6, fontSize: 13,
              background: actionMsg.ok ? '#f0fdf4' : '#fef2f2',
              border: `1px solid ${actionMsg.ok ? '#86efac' : '#fca5a5'}`,
              color: actionMsg.ok ? '#166534' : '#991b1b',
              display: 'flex', alignItems: 'center', gap: 6,
            }}>
              {actionMsg.ok ? '✅' : '❌'} {actionMsg.text}
            </div>
          )}
        </div>
      </div>

      {/* ── Governance History ──────────────────────────────────────────────── */}
      {gov?.actions?.length > 0 && (
        <SectionCard title="Governance History" icon="📜">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: '#f8fafc' }}>
                {['Decision', 'Approved', 'Time'].map(h => (
                  <th key={h} style={{
                    padding: '6px 10px', textAlign: 'left',
                    fontWeight: 600, color: '#475569',
                    borderBottom: '2px solid #e2e8f0',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {gov.actions.map((a, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                  <td style={{ padding: '6px 10px', color: '#1e293b' }}>{a.decision}</td>
                  <td style={{ padding: '6px 10px' }}>
                    {a.approved === true  ? <span style={{ color: '#22c55e' }}>✓ Yes</span>
                   : a.approved === false ? <span style={{ color: '#ef4444' }}>✗ No</span>
                   : <span style={{ color: '#94a3b8' }}>—</span>}
                  </td>
                  <td style={{ padding: '6px 10px', color: '#94a3b8' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleTimeString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

    </div>
  )
}

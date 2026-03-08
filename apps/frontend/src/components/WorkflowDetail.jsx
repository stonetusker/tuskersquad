import React, { useEffect, useState, useCallback } from 'react'
import api from '../api'
import FindingsList from './FindingsList'
import AgentsTimeline from './AgentsTimeline'
import AgentGraph from './AgentGraph'
import RiskHeatmap from './RiskHeatmap'
import LLMReasoningViewer from './LLMReasoningViewer'

const DASH_BASE = import.meta.env.VITE_DASH_URL || 'http://localhost:8501'

const STATUS_CFG = {
  COMPLETED:              { badge: 'badge-ok',     label: 'Completed'         },
  WAITING_HUMAN_APPROVAL: { badge: 'badge-yellow', label: 'Awaiting Decision'  },
  RUNNING:                { badge: 'badge-running', label: 'Running'           },
  FAILED:                 { badge: 'badge-err',    label: 'Failed'             },
}

const MERGE_CFG = {
  pending:  { icon: '⏳', color: '#f59e0b', label: 'Merging…'       },
  success:  { icon: '🔀', color: '#22c55e', label: 'Merged'          },
  failed:   { icon: '❌', color: '#ef4444', label: 'Merge failed'    },
  skipped:  { icon: '—',  color: '#94a3b8', label: 'Merge skipped'   },
}

const DEPLOY_CFG = {
  pending:   { icon: '⏳', color: '#f59e0b', label: 'Deploying…'         },
  triggered: { icon: '🚀', color: '#22c55e', label: 'Deploy triggered'   },
  failed:    { icon: '❌', color: '#ef4444', label: 'Deploy failed'       },
  skipped:   { icon: '—',  color: '#94a3b8', label: 'Deploy skipped'     },
}

function StatusBadge({ status }) {
  const cfg = STATUS_CFG[status] || { badge: 'badge-info', label: status || 'Unknown' }
  const isRunning = status === 'RUNNING'
  return (
    <span className={`badge ${cfg.badge}`} style={{ fontSize: 12, padding: '4px 12px' }}>
      {isRunning && (
        <span style={{
          width: 7, height: 7, borderRadius: '50%', background: 'currentColor',
          display: 'inline-block', marginRight: 5,
          animation: 'ts-pulse 1.2s ease-in-out infinite', opacity: 0.8,
        }} />
      )}
      {cfg.label}
    </span>
  )
}

function PanelCard({ title, icon, children, accent }) {
  return (
    <div className="panel" style={{ border: accent ? `1.5px solid ${accent}` : undefined }}>
      <div className="panel-header" style={{ gap: 7 }}>
        {icon && <span style={{ fontSize: 14 }}>{icon}</span>}
        {title}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

export default function WorkflowDetail({ workflowId }) {
  const [detail,       setDetail]       = useState(null)
  const [agents,       setAgents]       = useState([])
  const [findings,     setFindings]     = useState([])
  const [gov,          setGov]          = useState(null)
  const [qa,           setQa]           = useState(null)
  const [mergeStatus,  setMergeStatus]  = useState(null)
  const [deployStatus, setDeployStatus] = useState(null)
  const [deployUrl,    setDeployUrl]    = useState('')
  const [busy,         setBusy]         = useState(false)
  const [actionMsg,    setActionMsg]    = useState(null)
  const [releaseReason,setReleaseReason]= useState('')
  const [showRelease,  setShowRelease]  = useState(false)
  const [activeTab,    setActiveTab]    = useState('graph') // graph | timeline | heatmap | reasoning

  const isWaiting  = detail?.status === 'WAITING_HUMAN_APPROVAL'
  const isRunning  = detail?.status === 'RUNNING'
  const isDone     = detail?.status === 'COMPLETED'
  const isMerging  = mergeStatus === 'pending'
  const isDeploying= deployStatus === 'pending'
  const anyBusy    = busy || isMerging || isDeploying

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
      setAgents(a || [])
      setFindings(f || [])
      setGov(g)
      setQa(q)
      if (d?.merge_status  != null) setMergeStatus(d.merge_status)
      if (d?.deploy_status != null) setDeployStatus(d.deploy_status)
      if (d?.deploy_url)            setDeployUrl(d.deploy_url)
    } catch (e) {
      console.error('WorkflowDetail load error:', e)
    }
  }, [workflowId])

  const pollMergeDeploy = useCallback(async () => {
    if (!workflowId) return
    try {
      const r = await fetch(`${DASH_BASE}/api/ui/workflow/${workflowId}/merge-status`)
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
    const t = setInterval(load, 4000)
    return () => clearInterval(t)
  }, [workflowId, load])

  useEffect(() => {
    if (!isMerging && !isDeploying) return
    const t = setInterval(pollMergeDeploy, 1500)
    return () => clearInterval(t)
  }, [isMerging, isDeploying, pollMergeDeploy])

  async function doAction(fn, label) {
    setBusy(true)
    setActionMsg(null)
    try {
      const res = await fn()
      setActionMsg({ text: `${label} — ${res?.status || 'done'}`, ok: true })
      if (res?.status) setDetail(d => d ? { ...d, status: res.status } : d)
      if (res?.auto_merge_queued) { setMergeStatus('pending'); setTimeout(pollMergeDeploy, 800) }
      if (res?.deploy_queued)     setDeployStatus('pending')
    } catch (e) {
      setActionMsg({ text: `Error: ${e.message}`, ok: false })
    }
    setBusy(false)
  }

  if (!detail) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">⚙️</div>
        <div className="empty-state-text">Loading workflow…</div>
      </div>
    )
  }

  const rationale = detail?.rationale || gov?.rationale
  const mc = MERGE_CFG[mergeStatus]
  const dc = DEPLOY_CFG[deployStatus]

  const TABS = [
    { id: 'graph',     label: '🔗 Agent Graph' },
    { id: 'timeline',  label: '⏱ Timeline' },
    { id: 'heatmap',   label: '🌡 Risk Heatmap' },
    { id: 'reasoning', label: '🧠 LLM Reasoning' },
  ]

  return (
    <div className="animate-in" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

      {/* ── Header ── */}
      <div className="detail-header">
        <div>
          <div className="detail-id">#{workflowId.slice(0, 8)}</div>
          <div className="detail-repo">
            {detail.repository}
            <span className="detail-pr"> PR #{detail.pr_number}</span>
          </div>
          <div className="detail-time">
            {detail.created_at ? new Date(detail.created_at).toLocaleString() : ''}
          </div>
        </div>
        <StatusBadge status={detail.status} />
      </div>

      {/* ── Merge/Deploy Banner ── */}
      {(mc || dc) && (
        <div className="merge-banner">
          {mc && (
            <div className="merge-banner-item" style={{ color: mc.color }}>
              {mc.icon} <span>{mc.label}</span>
            </div>
          )}
          {mc && dc && <span className="sep">·</span>}
          {dc && (
            <div className="merge-banner-item" style={{ color: dc.color }}>
              {dc.icon}
              {deployStatus === 'triggered' && deployUrl
                ? <a href={deployUrl} target="_blank" rel="noreferrer" style={{ color: dc.color }}>
                    {dc.label} ↗
                  </a>
                : <span>{dc.label}</span>
              }
            </div>
          )}
        </div>
      )}

      {/* ── Governance Bar ── */}
      <div className={`gov-bar ${isWaiting ? 'awaiting' : ''}`}>
        <div className="gov-bar-head">
          <span style={{ fontSize: 16 }}>{isWaiting ? '⏸️' : isDone ? '✅' : '⚙️'}</span>
          Human Governance
          {isWaiting && <span className="badge badge-yellow" style={{ fontSize: 10 }}>AWAITING DECISION</span>}
        </div>
        <div className="gov-bar-body">
          <div className="action-row">
            <button className="btn btn-approve" disabled={anyBusy}
              onClick={() => doAction(() => api.approveWorkflow(workflowId), 'Approved')}
              title="Approve — triggers auto-merge if enabled">
              ✓ Approve
            </button>
            <button className="btn btn-reject" disabled={anyBusy}
              onClick={() => doAction(() => api.rejectWorkflow(workflowId), 'Rejected')}>
              ✗ Reject
            </button>
            <button className="btn btn-retest" disabled={anyBusy}
              onClick={() => doAction(() => api.retestWorkflow(workflowId), 'Retest queued')}>
              ↺ Retest
            </button>
            <button className="btn btn-release" disabled={anyBusy}
              onClick={() => setShowRelease(v => !v)}>
              ⚡ Override
            </button>
          </div>

          {isWaiting && (
            <div className="hint-bar">
              🔀 <strong>Approve</strong> will auto-merge this PR and trigger deploy if configured.
            </div>
          )}

          {showRelease && (
            <div className="release-panel">
              <h4>⚡ Release Manager Override</h4>
              <p>Overrides AI governance. Business justification is required and will be posted to the PR.</p>
              <input
                placeholder="Business justification (required)…"
                value={releaseReason}
                onChange={e => setReleaseReason(e.target.value)}
              />
              <div className="action-row">
                <button className="btn btn-approve" disabled={anyBusy}
                  onClick={() => doAction(
                    () => api.releaseManagerOverride(workflowId, 'APPROVE', releaseReason || 'Release Manager override'),
                    'Force approved'
                  )}>Force Approve</button>
                <button className="btn btn-reject" disabled={anyBusy}
                  onClick={() => doAction(
                    () => api.releaseManagerOverride(workflowId, 'REJECT', releaseReason || 'Release Manager override'),
                    'Force rejected'
                  )}>Force Reject</button>
              </div>
            </div>
          )}

          {actionMsg && (
            <div className={`action-msg ${actionMsg.ok ? 'ok' : 'err'}`}>
              {actionMsg.ok ? '✅' : '❌'} {actionMsg.text}
            </div>
          )}
        </div>
      </div>

      {/* ── Findings + QA row ── */}
      <div className="detail-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <PanelCard title={`Findings (${findings.length})`} icon="🔍">
          <FindingsList findings={findings} />
        </PanelCard>

        <PanelCard title="QA Lead Summary" icon="📋">
          {qa ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                <span style={{ fontSize: 11, color: '#64748b' }}>Risk:</span>
                <span className={`badge ${
                  qa.risk_level === 'HIGH'   ? 'badge-err' :
                  qa.risk_level === 'MEDIUM' ? 'badge-warn' : 'badge-ok'
                }`}>{qa.risk_level}</span>
              </div>
              <pre className="qa-summary">{qa.summary}</pre>
            </>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: 12 }}>
              {isRunning ? 'QA summary generating…' : 'No QA summary yet'}
            </div>
          )}
        </PanelCard>
      </div>

      {/* ── Tabbed View: Graph / Timeline / Heatmap / Reasoning ── */}
      <div className="panel">
        {/* Tab bar */}
        <div style={{
          display: 'flex',
          background: '#f8fafc',
          borderBottom: '1px solid #e2e8f0',
          overflow: 'hidden',
          borderRadius: '10px 10px 0 0',
        }}>
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '10px 16px',
                border: 'none',
                background: activeTab === tab.id ? '#fff' : 'transparent',
                borderBottom: activeTab === tab.id ? '2px solid #FACF0E' : '2px solid transparent',
                cursor: 'pointer',
                fontSize: 12,
                fontWeight: 600,
                fontFamily: 'inherit',
                color: activeTab === tab.id ? '#2B2B2B' : '#94a3b8',
                transition: 'all 0.15s',
                flex: 1,
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="panel-body">
          {activeTab === 'graph' && (
            <AgentGraph agents={agents} currentAgent={detail.current_agent} />
          )}
          {activeTab === 'timeline' && (
            <AgentsTimeline agents={agents} currentAgent={detail.current_agent} />
          )}
          {activeTab === 'heatmap' && (
            <RiskHeatmap findings={findings} />
          )}
          {activeTab === 'reasoning' && (
            <LLMReasoningViewer
              rationale={rationale}
              qaSummary={qa?.summary}
              riskLevel={qa?.risk_level}
            />
          )}
        </div>
      </div>

      {/* ── Governance History ── */}
      {gov?.actions?.length > 0 && (
        <PanelCard title="Governance History" icon="📜">
          <table className="gov-history-table">
            <thead>
              <tr>
                <th>Decision</th>
                <th>Approved</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {gov.actions.map((a, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600 }}>{a.decision}</td>
                  <td>
                    {a.approved === true  ? <span style={{ color: '#22c55e' }}>✓ Yes</span>
                   : a.approved === false ? <span style={{ color: '#ef4444' }}>✗ No</span>
                   : <span style={{ color: '#94a3b8' }}>—</span>}
                  </td>
                  <td style={{ color: '#94a3b8' }}>
                    {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </PanelCard>
      )}
    </div>
  )
}

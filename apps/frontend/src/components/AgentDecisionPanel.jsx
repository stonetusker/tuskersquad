import { useState, useEffect } from 'react'
import api from '../api'

const AGENT_ICONS  = { planner:'🧭', backend:'⚙️', frontend:'🎨', security:'🔐', sre:'📡', challenger:'⚔️', qa_lead:'📋', judge:'⚖️' }
const AGENT_LABELS = { planner:'Planner', backend:'Backend Eng.', frontend:'Frontend Eng.', security:'Security Eng.', sre:'SRE', challenger:'Challenger', qa_lead:'QA Lead', judge:'Judge' }
const PIPELINE_ORDER = ['planner','backend','frontend','security','sre','challenger','qa_lead','judge']

const DECISION_STYLE = {
  APPROVE:         { bg:'#064e3b', color:'#6ee7b7', label:'✅ APPROVE' },
  REJECT:          { bg:'#7f1d1d', color:'#fca5a5', label:'❌ REJECT' },
  REVIEW_REQUIRED: { bg:'#78350f', color:'#fde68a', label:'⚠️ REVIEW' },
  PASS:            { bg:'#064e3b', color:'#6ee7b7', label:'🟢 PASS'   },
  FLAG:            { bg:'#7f1d1d', color:'#fca5a5', label:'🔴 FLAG'   },
  CHALLENGE:       { bg:'#1e1b4b', color:'#c7d2fe', label:'⚔️ CHALLENGE'},
}
const RISK_STYLE = {
  HIGH:  { color:'#ef4444' }, MEDIUM: { color:'#f59e0b' },
  LOW:   { color:'#22c55e' }, NONE:   { color:'#6b7280' },
}

export default function AgentDecisionPanel({ workflowId }) {
  const [decisions, setDecisions] = useState([])
  const [loading,   setLoading]   = useState(true)

  useEffect(() => {
    if (!workflowId) return
    api.getAgentDecisions(workflowId)
      .then(d => { setDecisions(d || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [workflowId])

  if (loading) return <div style={{padding:'1rem',color:'#9CA3AF'}}>Loading agent decisions…</div>

  if (!decisions.length) return (
    <div style={{padding:'1.5rem',color:'#9CA3AF',textAlign:'center'}}>
      <p style={{fontSize:'2rem'}}>⏳</p>
      <p>Agent decisions will appear once the pipeline completes.</p>
    </div>
  )

  const byAgent = {}
  for (const d of decisions) byAgent[d.agent] = d

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'0.6rem',padding:'0.5rem'}}>
      {PIPELINE_ORDER.map(agent => {
        const d = byAgent[agent]
        if (!d) return null
        const ds = DECISION_STYLE[d.decision] || { bg:'#374151', color:'#D1D5DB', label: d.decision }
        const rs = RISK_STYLE[d.risk_level]   || { color:'#6b7280' }
        return (
          <div key={agent} style={{
            background:'#1C1C1E',borderRadius:'8px',padding:'0.85rem 1rem',
            border:`1px solid ${ds.bg}`,
          }}>
            <div style={{display:'flex',alignItems:'center',gap:'0.6rem',marginBottom:'0.4rem'}}>
              <span style={{fontSize:'1.2rem'}}>{AGENT_ICONS[agent]||'🤖'}</span>
              <span style={{fontFamily:'Space Mono,monospace',fontWeight:'bold',color:'#F3F4F6',fontSize:'0.85rem'}}>
                {AGENT_LABELS[agent] || agent}
              </span>
              <span style={{
                marginLeft:'auto',padding:'0.15rem 0.6rem',borderRadius:'10px',fontSize:'0.72rem',
                background: ds.bg, color: ds.color, fontWeight:'bold',
              }}>{ds.label}</span>
              <span style={{fontSize:'0.75rem',fontWeight:'bold',color: rs.color}}>
                {d.risk_level}
              </span>
            </div>
            {d.summary && (
              <p style={{fontSize:'0.8rem',color:'#9CA3AF',margin:'0 0 0.3rem 1.9rem',lineHeight:1.4}}>
                {d.summary}
              </p>
            )}
            <div style={{fontSize:'0.72rem',color:'#4B5563',marginLeft:'1.9rem'}}>
              Tests run: {d.test_count || 0}
            </div>
          </div>
        )
      })}
    </div>
  )
}

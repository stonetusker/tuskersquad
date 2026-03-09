import { useState, useEffect, useRef } from 'react'
import api from '../api'

const AGENT_ICONS = {
  planner:'🧭', backend:'⚙️', frontend:'🎨', security:'🔐',
  sre:'📡', challenger:'⚔️', qa_lead:'📋', judge:'⚖️',
}

export default function LLMLogsViewer({ workflowId }) {
  const [logs, setLogs]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [expanded, setExpanded] = useState({})
  const [filter, setFilter]     = useState('all')

  useEffect(() => {
    if (!workflowId) return
    api.getLLMLogs(workflowId)
      .then(data => { setLogs(data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }, [workflowId])

  const agents = ['all', ...new Set(logs.map(l => l.agent))]
  const visible = filter === 'all' ? logs : logs.filter(l => l.agent === filter)

  const toggle = (id) => setExpanded(e => ({ ...e, [id]: !e[id] }))

  if (loading) return <div className="reasoning-viewer" style={{padding:'1rem',color:'#9CA3AF'}}>Loading LLM logs…</div>

  if (!logs.length) return (
    <div className="reasoning-viewer" style={{padding:'1.5rem',color:'#9CA3AF',textAlign:'center'}}>
      <p style={{fontSize:'2rem',marginBottom:'0.5rem'}}>📭</p>
      <p>No LLM conversations recorded yet.</p>
      <p style={{fontSize:'0.8rem',marginTop:'0.5rem'}}>LLM logs appear when Ollama is configured and agents invoke the model.</p>
    </div>
  )

  return (
    <div className="reasoning-viewer" style={{padding:'1rem',overflow:'auto',maxHeight:'520px'}}>
      {/* filter pills */}
      <div style={{display:'flex',gap:'0.5rem',marginBottom:'1rem',flexWrap:'wrap'}}>
        {agents.map(a => (
          <button key={a} onClick={() => setFilter(a)}
            style={{
              padding:'0.2rem 0.7rem',borderRadius:'12px',fontSize:'0.75rem',cursor:'pointer',border:'none',
              background: filter===a ? '#FACF0E' : '#374151',
              color: filter===a ? '#1a1a1a' : '#D1D5DB',
              fontFamily:'Space Mono, monospace',
            }}>
            {a === 'all' ? 'ALL' : `${AGENT_ICONS[a]||''} ${a}`}
          </button>
        ))}
        <span style={{marginLeft:'auto',fontSize:'0.75rem',color:'#6B7280',alignSelf:'center'}}>
          {visible.length} conversation{visible.length!==1?'s':''}
        </span>
      </div>

      {/* log entries */}
      {visible.map((log, i) => {
        const open = expanded[log.id || i]
        const ok   = log.success !== false
        return (
          <div key={log.id || i} style={{
            marginBottom:'0.75rem',borderRadius:'6px',overflow:'hidden',
            border: `1px solid ${ok ? '#374151' : '#7f1d1d'}`,
          }}>
            {/* header row */}
            <div onClick={() => toggle(log.id || i)} style={{
              display:'flex',alignItems:'center',gap:'0.75rem',
              padding:'0.6rem 0.8rem',cursor:'pointer',
              background: ok ? '#1C1C1E' : '#2d1515',
            }}>
              <span style={{fontSize:'1.1rem'}}>{AGENT_ICONS[log.agent]||'🤖'}</span>
              <span style={{fontFamily:'Space Mono,monospace',color:'#FACF0E',fontSize:'0.8rem',fontWeight:'bold'}}>
                {log.agent}
              </span>
              <span style={{fontSize:'0.75rem',color:'#6B7280'}}>model: {log.model}</span>
              {log.duration_ms != null && (
                <span style={{fontSize:'0.72rem',color:'#4B5563',marginLeft:'auto'}}>
                  ⏱ {log.duration_ms}ms
                </span>
              )}
              <span style={{
                fontSize:'0.7rem',padding:'0.1rem 0.5rem',borderRadius:'8px',
                background: ok ? '#064e3b' : '#7f1d1d',
                color: ok ? '#6ee7b7' : '#fca5a5',
              }}>{ok ? '✓ OK' : '✗ ERR'}</span>
              <span style={{fontSize:'0.7rem',color:'#6B7280'}}>{open ? '▲' : '▼'}</span>
            </div>

            {/* expanded body */}
            {open && (
              <div style={{padding:'0.8rem',background:'#111',borderTop:'1px solid #374151'}}>
                <div style={{marginBottom:'0.5rem'}}>
                  <div style={{fontSize:'0.7rem',color:'#9CA3AF',marginBottom:'0.25rem',textTransform:'uppercase',letterSpacing:'0.05em'}}>
                    Prompt
                  </div>
                  <pre style={{
                    fontSize:'0.75rem',color:'#D1FAE5',whiteSpace:'pre-wrap',wordBreak:'break-word',
                    background:'#0d1117',padding:'0.6rem',borderRadius:'4px',margin:0,maxHeight:'200px',overflow:'auto',
                  }}>{log.prompt || '(empty)'}</pre>
                </div>
                <div>
                  <div style={{fontSize:'0.7rem',color:'#9CA3AF',marginBottom:'0.25rem',textTransform:'uppercase',letterSpacing:'0.05em'}}>
                    Response
                  </div>
                  <pre style={{
                    fontSize:'0.75rem',color: ok ? '#BAE6FD' : '#FCA5A5',whiteSpace:'pre-wrap',wordBreak:'break-word',
                    background:'#0d1117',padding:'0.6rem',borderRadius:'4px',margin:0,maxHeight:'240px',overflow:'auto',
                  }}>{log.error || log.response || '(no response)'}</pre>
                </div>
                <div style={{marginTop:'0.4rem',fontSize:'0.7rem',color:'#4B5563'}}>
                  {log.created_at && new Date(log.created_at).toLocaleString()}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

import React from 'react'

export default function AgentsTimeline({agents}){
  if(!agents || agents.length===0) return <div className="muted">No agent data</div>
  return (
    <ul className="agents-list">
      {agents.map((a,idx)=> (
        <li key={idx} className={`agent ${a.status||''}`}>
          <div className="agent-name">{a.agent}</div>
          <div className="agent-meta">{a.status} · {a.started_at? new Date(a.started_at).toLocaleTimeString() : ''}</div>
          <div className="agent-log">{a.output || ''}</div>
        </li>
      ))}
    </ul>
  )
}

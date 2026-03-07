import React from 'react'

export default function FindingsList({findings}){
  if(!findings || findings.length===0) return <div className="muted">No findings</div>
  return (
    <ul className="findings-list">
      {findings.map(f => (
        <li key={f.id} className={`finding ${f.severity||''}`}>
          <div className="title">{f.title}</div>
          <div className="meta">{f.agent} • {f.severity}</div>
          <div className="desc">{f.description}</div>
        </li>
      ))}
    </ul>
  )
}

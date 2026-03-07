import React, {useEffect, useState} from 'react'
import api from '../api'

export default function WorkflowList({onSelect, selectedId}){
  const [list, setList] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(()=>{
    let mounted = true
    async function load(){
      setLoading(true)
      try{
        const data = await api.listWorkflows()
        if(mounted) setList(data || [])
      }catch(e){
        console.error(e)
      }finally{ setLoading(false) }
    }
    load()
    const t = setInterval(load, 4000)
    return ()=>{ mounted = false; clearInterval(t) }
  }, [])

  return (
    <div className="panel workflows">
      <h3>Workflows</h3>
      {loading && <div className="muted">Refreshing...</div>}
      <ul className="workflow-list">
        {list.map(w => (
          <li key={w.workflow_id} className={w.workflow_id===selectedId? 'selected':''} onClick={()=>onSelect && onSelect(w.workflow_id)}>
            <div className="wf-title">{w.repository}#{w.pr_number}</div>
            <div className="wf-meta">{w.status} · {new Date(w.created_at).toLocaleTimeString()}</div>
          </li>
        ))}
      </ul>
      {list.length===0 && <div className="muted">No workflows yet — start one from the Control Panel.</div>}
    </div>
  )
}


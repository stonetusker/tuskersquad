import React, {useEffect, useState} from 'react'
import api from '../api'
import FindingsList from './FindingsList'
import AgentsTimeline from './AgentsTimeline'

export default function WorkflowDetail({workflowId}){
  const [detail, setDetail] = useState(null)
  const [agents, setAgents] = useState([])
  const [findings, setFindings] = useState([])
  const [gov, setGov] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(()=>{
    if(!workflowId) return
    let mounted = true
    async function load(){
      try{
        const d = await api.getWorkflow(workflowId)
        const a = await api.getAgents(workflowId)
        const f = await api.getFindings(workflowId)
        const g = await api.getGovernance(workflowId)
        if(mounted){ setDetail(d); setAgents(a||[]); setFindings(f||[]); setGov(g) }
      }catch(e){ console.error(e) }
    }
    load()
    const t = setInterval(load, 4000)
    return ()=>{ mounted=false; clearInterval(t) }
  }, [workflowId])

  async function doApprove(){
    setBusy(true)
    try{ await api.approveWorkflow(workflowId); }catch(e){ console.error(e) }
    setBusy(false)
  }

  async function doReject(){
    setBusy(true)
    try{ await api.rejectWorkflow(workflowId); }catch(e){ console.error(e) }
    setBusy(false)
  }

  if(!detail) return <div className="panel">Loading workflow...</div>

  return (
    <div className="panel detail">
      <h3>Workflow</h3>
      <div className="wf-header">
        <div className="wf-id">{detail.workflow_id}</div>
        <div className="wf-status">{detail.status}</div>
      </div>
      <div className="wf-grid">
        <div className="wf-col">
          <h4>Agents</h4>
          <AgentsTimeline agents={agents} />
        </div>
        <div className="wf-col">
          <h4>Findings</h4>
          <FindingsList findings={findings} />
        </div>
        <div className="wf-col">
          <h4>Governance</h4>
          {detail && detail.rationale ? (
            <div className="governance">
              <div><strong>Auto-decision rationale (LLM):</strong></div>
              <pre>{detail.rationale}</pre>
            </div>
          ) : (gov && gov.rationale ? (
            <div className="governance">
              <div><strong>Auto-decision rationale (LLM):</strong></div>
              <pre>{gov.rationale}</pre>
            </div>
          ) : null)}
        </div>
      </div>
      <div className="wf-actions">
        <button onClick={doApprove} disabled={busy}>Approve</button>
        <button onClick={doReject} disabled={busy}>Reject</button>
      </div>
    </div>
  )
}

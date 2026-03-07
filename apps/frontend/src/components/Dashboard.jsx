import React, {useState} from 'react'
import ControlPanel from './ControlPanel'
import WorkflowList from './WorkflowList'
import WorkflowDetail from './WorkflowDetail'

export default function Dashboard() {
  const [selected, setSelected] = useState(null)

  return (
    <div className="dashboard-root">
      <div className="dashboard-left">
        <ControlPanel onStarted={(wf) => setSelected(wf?.workflow_id)} />
        <WorkflowList onSelect={(id) => setSelected(id)} selectedId={selected} />
      </div>
      <div className="dashboard-right">
        {selected ? <WorkflowDetail workflowId={selected} /> : <div className="empty">Select a workflow to view details</div>}
      </div>
    </div>
  )
}

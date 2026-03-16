import React, { useState } from 'react'
import ControlPanel from './ControlPanel'
import WorkflowList from './WorkflowList'
import WorkflowDetail from './WorkflowDetail'
import OllamaBanner from './OllamaBanner'

export default function Dashboard() {
  const [selected, setSelected] = useState(null)

  return (
    <div className="dashboard-root">
      <div className="dashboard-left">
        <OllamaBanner />
        <ControlPanel onStarted={(wf) => wf?.workflow_id && setSelected(wf.workflow_id)} />
        <WorkflowList onSelect={setSelected} selectedId={selected} />
      </div>
      <div className="dashboard-right">
        {selected
          ? <WorkflowDetail workflowId={selected} />
          : (
            <div className="empty-state">
              <div className="empty-state-icon">—</div>
              <div className="empty-state-text">Select a review to inspect</div>
              <div className="empty-state-sub">or start a new PR review on the left</div>
            </div>
          )
        }
      </div>
    </div>
  )
}

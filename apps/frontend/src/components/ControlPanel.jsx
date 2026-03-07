import React, {useState} from 'react'
import api from '../api'

export default function ControlPanel({onStarted}){
  const [repo, setRepo] = useState('example/hello')
  const [pr, setPr] = useState(42)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  async function start(){
    setBusy(true)
    setMsg('')
    try {
      const res = await api.simulateWebhook({repo, pr_number: Number(pr)})
      setMsg(JSON.stringify(res))
      if(onStarted) onStarted(res)
    } catch(e){
      setMsg(String(e))
    } finally { setBusy(false) }
  }

  return (
    <div className="panel control">
      <h3>Control Panel</h3>
      <div className="form-row">
        <label>Repository</label>
        <input value={repo} onChange={e=>setRepo(e.target.value)} />
      </div>
      <div className="form-row">
        <label>PR Number</label>
        <input type="number" value={pr} onChange={e=>setPr(e.target.value)} />
      </div>
      <div className="form-row actions">
        <button onClick={start} disabled={busy}>Start Workflow</button>
      </div>
      <div className="status">{msg}</div>
    </div>
  )
}

import React from 'react'
import './App.css'
import Dashboard from './components/Dashboard'

export default function App() {
  return (
    <div className="app-root">
      <header className="app-header">
        <div className="brand">TuskerSquad</div>
        <div className="tag">AI Engineering Governance</div>
      </header>
      <main className="app-main">
        <Dashboard />
      </main>
    </div>
  )
}


import React from 'react'
import './App.css'
import Dashboard from './components/Dashboard'

export default function App() {
  return (
    <div className="app-root">
      <header className="app-header">
        <div className="brand-block">
          <svg className="brand-icon" width="32" height="32" viewBox="0 0 32 32" fill="none">
            <rect width="32" height="32" rx="8" fill="#FACF0E"/>
            <path d="M8 16 L16 6 L24 16 L16 26 Z" fill="none" stroke="#202123" strokeWidth="2.5" strokeLinejoin="round"/>
            <circle cx="16" cy="16" r="3.5" fill="#202123"/>
            <circle cx="16" cy="6"  r="2" fill="#202123"/>
            <circle cx="24" cy="16" r="2" fill="#202123"/>
            <circle cx="16" cy="26" r="2" fill="#202123"/>
            <circle cx="8"  cy="16" r="2" fill="#202123"/>
          </svg>
          <div className="brand-text">
            <span className="brand-name">TuskerSquad</span>
            <span className="brand-tag">AI PR Governance</span>
          </div>
        </div>

        <nav className="header-nav">
          <span className="nav-pill active">Dashboard</span>
        </nav>

        <div className="header-status">
          <span className="status-dot pulsing" />
          <span className="status-text">8 Agents Active</span>
        </div>
      </header>

      <main className="app-main">
        <Dashboard />
      </main>
    </div>
  )
}

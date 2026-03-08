import React from 'react'
import './App.css'
import Dashboard from './components/Dashboard'

export default function App() {
  return (
    <div className="app-root">
      <header className="app-header">
        <div className="brand-block">
          {/* Logo mark */}
          <div className="logo-mark">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <rect width="28" height="28" rx="6" fill="#00b4d8"/>
              <path d="M7 14 L14 7 L21 14 L14 21 Z"
                    fill="none" stroke="#0b1220" strokeWidth="2.5"
                    strokeLinejoin="round"/>
              <circle cx="14" cy="14" r="3" fill="#0b1220"/>
            </svg>
          </div>
          <div>
            <div className="brand-name">
              Stonetusker Systems
            </div>
            <div className="brand-sub">TuskerSquad · Agentic AI Governance</div>
          </div>
        </div>

        <div className="header-right">
          <div className="pipeline-label">
            <span className="pipeline-dot" />
            8-Agent AI Pipeline
          </div>
        </div>
      </header>

      <main className="app-main">
        <Dashboard />
      </main>
    </div>
  )
}

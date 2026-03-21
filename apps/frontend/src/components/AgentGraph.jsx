/**
 * AgentGraph — Live SVG execution graph showing agent pipeline state
 * Nodes: pending → active (pulsing yellow) → completed (green) → failed (red)
 * Edges animate as each agent completes.
 */
import React, { useMemo } from 'react'

const AGENTS = [
  // Repository validation
  { id: 'repo_validator', label: 'Repo Validator', icon: 'RV', x: 200, y: 10 },

  // Planning phase
  { id: 'planner', label: 'Planner', icon: 'PL', x: 200, y: 70 },

  // Client-side testing
  { id: 'backend', label: 'Backend', icon: 'BE', x: 50, y: 130 },
  { id: 'frontend', label: 'Frontend', icon: 'FE', x: 200, y: 130 },
  { id: 'security', label: 'Security', icon: 'SEC', x: 350, y: 130 },
  { id: 'sre', label: 'SRE', icon: 'SRE', x: 200, y: 190 },

  // Build & Deploy
  { id: 'builder', label: 'Builder', icon: 'BLD', x: 50, y: 250 },
  { id: 'deployer', label: 'Deployer', icon: 'DEP', x: 200, y: 250 },
  { id: 'tester', label: 'Tester', icon: 'TST', x: 350, y: 250 },

  // Runtime validation
  { id: 'api_validator', label: 'API Validator', icon: 'API', x: 50, y: 310 },
  { id: 'security_runtime', label: 'Security Runtime', icon: 'SEC-R', x: 200, y: 310 },
  { id: 'runtime_analyzer', label: 'Runtime Analyzer', icon: 'RNA', x: 350, y: 310 },

  // Log analysis & correlation
  { id: 'log_inspector', label: 'Log Inspector', icon: 'LOG', x: 125, y: 370 },
  { id: 'correlator', label: 'Correlator', icon: 'COR', x: 275, y: 370 },

  // Review & decision
  { id: 'challenger', label: 'Challenger', icon: 'CH', x: 125, y: 430 },
  { id: 'qa_lead', label: 'QA Lead', icon: 'QA', x: 200, y: 490 },
  { id: 'judge', label: 'Judge', icon: 'JDG', x: 200, y: 550 },

  // Human interaction & cleanup
  { id: 'human_approval', label: 'Human Approval', icon: 'HUM', x: 350, y: 550 },
  { id: 'cleanup', label: 'Cleanup', icon: 'CLN', x: 200, y: 610 },
]

const EDGES = [
  // Initial validation
  ['repo_validator', 'planner'],

  // Sequential client-side testing
  ['planner', 'backend'],
  ['backend', 'frontend'],
  ['frontend', 'security'],
  ['security', 'sre'],

  // Build & deploy sequence
  ['sre', 'builder'],
  ['builder', 'deployer'],
  ['deployer', 'tester'],

  // Runtime validation sequence
  ['tester', 'api_validator'],
  ['api_validator', 'security_runtime'],
  ['security_runtime', 'runtime_analyzer'],

  // Log analysis & correlation
  ['runtime_analyzer', 'log_inspector'],
  ['log_inspector', 'correlator'],

  // Review & decision
  ['correlator', 'challenger'],
  ['challenger', 'qa_lead'],
  ['qa_lead', 'judge'],

  // Judge outcomes
  ['judge', 'human_approval'],
  ['judge', 'cleanup'],

  // Human approval to cleanup
  ['human_approval', 'cleanup'],
]

const NODE_W = 88
const NODE_H = 32

export default function AgentGraph({ agents, currentAgent }) {
  const stateMap = useMemo(() => {
    const m = {}
    AGENTS.forEach(a => { m[a.id] = 'pending' })
    if (agents) {
      agents.forEach(a => {
        if (a.status === 'COMPLETED') m[a.agent] = 'completed'
        else if (a.status === 'FAILED')    m[a.agent] = 'failed'
        else if (a.status === 'RUNNING')   m[a.agent] = 'active'
      })
    }
    if (currentAgent) m[currentAgent] = 'active'
    return m
  }, [agents, currentAgent])

  const edgeState = (from, to) => {
    if (stateMap[from] === 'completed') return 'done'
    if (stateMap[from] === 'active')    return 'active'
    return 'pending'
  }

  const nodePos = (id) => AGENTS.find(a => a.id === id)

  const nodeColour = (state) => {
    if (state === 'active')    return { fill: '#fffbea', stroke: '#FACF0E', sw: 2.5, tc: '#92400e' }
    if (state === 'completed') return { fill: '#f0fdf4', stroke: '#22c55e', sw: 1.5, tc: '#15803d' }
    if (state === 'failed')    return { fill: '#fee2e2', stroke: '#ef4444', sw: 1.5, tc: '#991b1b' }
    return { fill: '#fff', stroke: '#d1d5db', sw: 1, tc: '#9ca3af' }
  }

  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <svg
        viewBox="0 0 450 650"
        style={{ width: '100%', maxWidth: 450, display: 'block', margin: '0 auto' }}
      >
        <defs>
          <marker id="arrowhead" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#d1d5db" />
          </marker>
          <marker id="arrowhead-done" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#22c55e" />
          </marker>
          <marker id="arrowhead-active" markerWidth="8" markerHeight="6" refX="6" refY="3" orient="auto">
            <polygon points="0 0, 8 3, 0 6" fill="#FACF0E" />
          </marker>
        </defs>

        {/* Edges */}
        {EDGES.map(([from, to], i) => {
          const a = nodePos(from)
          const b = nodePos(to)
          if (!a || !b) return null
          const ax = a.x + NODE_W / 2
          const ay = a.y + NODE_H
          const bx = b.x + NODE_W / 2
          const by = b.y
          const state = edgeState(from, to)
          const stroke = state === 'done' ? '#22c55e' : state === 'active' ? '#FACF0E' : '#d1d5db'
          const mId = state === 'done' ? 'arrowhead-done' : state === 'active' ? 'arrowhead-active' : 'arrowhead'
          const cy = (ay + by) / 2
          return (
            <path
              key={i}
              d={`M${ax},${ay} C${ax},${cy} ${bx},${cy} ${bx},${by}`}
              stroke={stroke}
              strokeWidth={state !== 'pending' ? 1.8 : 1}
              fill="none"
              markerEnd={`url(#${mId})`}
              opacity={state === 'pending' ? 0.35 : 1}
              style={{ transition: 'stroke 0.4s' }}
            />
          )
        })}

        {/* Nodes */}
        {AGENTS.map(a => {
          const state = stateMap[a.id]
          const c = nodeColour(state)
          const isActive = state === 'active'
          return (
            <g key={a.id}>
              {isActive && (
                <rect
                  x={a.x - 3} y={a.y - 3}
                  width={NODE_W + 6} height={NODE_H + 6}
                  rx={9} fill="none"
                  stroke="#FACF0E" strokeWidth="2"
                  opacity="0.5"
                  style={{ animation: 'ts-pulse 1.2s ease-in-out infinite' }}
                />
              )}
              <rect
                x={a.x} y={a.y}
                width={NODE_W} height={NODE_H}
                rx={7}
                fill={c.fill}
                stroke={c.stroke}
                strokeWidth={c.sw}
                style={{ transition: 'all 0.3s' }}
              />
              <text
                x={a.x + NODE_W / 2}
                y={a.y + NODE_H / 2 - 1}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize="11"
                fontWeight="600"
                fill={c.tc}
                style={{ fontFamily: "'DM Sans', sans-serif" }}
              >
                {a.icon} {a.label}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 8, flexWrap: 'wrap' }}>
        {[
          { color: '#FACF0E', bg: '#fffbea', label: 'Running' },
          { color: '#22c55e', bg: '#f0fdf4', label: 'Complete' },
          { color: '#ef4444', bg: '#fee2e2', label: 'Failed' },
          { color: '#d1d5db', bg: '#fff',    label: 'Pending' },
        ].map(({ color, bg, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: '#6b7280' }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: bg, border: `1.5px solid ${color}`, display: 'inline-block' }} />
            {label}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * AgentGraph — Live SVG execution graph showing agent pipeline state
 * Nodes: pending → active (pulsing yellow) → completed (green) → failed (red)
 * Edges animate as each agent completes.
 */
import React, { useMemo } from 'react'

const AGENTS = [
  { id: 'planner',    label: 'Planner',    icon: '🧭', x: 130, y: 20  },
  { id: 'backend',    label: 'Backend',    icon: '⚙️',  x: 20,  y: 90  },
  { id: 'frontend',   label: 'Frontend',   icon: '🎨',  x: 130, y: 90  },
  { id: 'security',   label: 'Security',   icon: '🔐',  x: 240, y: 90  },
  { id: 'sre',        label: 'SRE',        icon: '📡',  x: 350, y: 90  },
  { id: 'challenger', label: 'Challenger', icon: '⚔️',  x: 185, y: 160 },
  { id: 'qa_lead',    label: 'QA Lead',    icon: '📋',  x: 185, y: 230 },
  { id: 'judge',      label: 'Judge',      icon: '⚖️',  x: 185, y: 300 },
]

const EDGES = [
  ['planner', 'backend'],
  ['planner', 'frontend'],
  ['planner', 'security'],
  ['planner', 'sre'],
  ['backend',    'challenger'],
  ['frontend',   'challenger'],
  ['security',   'challenger'],
  ['sre',        'challenger'],
  ['challenger', 'qa_lead'],
  ['qa_lead',    'judge'],
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
        viewBox="0 0 460 345"
        style={{ width: '100%', maxWidth: 460, display: 'block', margin: '0 auto' }}
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

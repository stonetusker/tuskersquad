/**
 * LLMReasoningViewer — Shows judge rationale + QA summary as "live" LLM output
 * with colour-coded tokens and a typewriter effect when content first appears.
 */
import React, { useEffect, useRef, useState } from 'react'

function colourLine(line) {
  if (!line.trim()) return <br />
  if (line.startsWith('[') && line.includes(']')) {
    // [AGENT] header
    return <span className="line-agent">{line}</span>
  }
  const upper = line.toUpperCase()
  if (upper.includes('APPROVE') || upper.includes('PASS') || upper.includes('OK')) {
    return <span className="line-decision">{line}</span>
  }
  if (upper.includes('REVIEW') || upper.includes('RISK') || upper.includes('CONCERN') || upper.includes('FAIL')) {
    return <span className="line-think">{line}</span>
  }
  return <span>{line}</span>
}

export default function LLMReasoningViewer({ rationale, qaSummary, riskLevel }) {
  const ref = useRef(null)
  const [shown, setShown] = useState(0)

  const fullText = [
    rationale && `[JUDGE AGENT] Reasoning\n${rationale}`,
    qaSummary && `\n[QA LEAD] Summary — Risk: ${riskLevel || 'UNKNOWN'}\n${qaSummary}`,
  ].filter(Boolean).join('\n')

  // Typewriter effect: reveal 4 chars at a time
  useEffect(() => {
    if (!fullText) return
    setShown(0)
    const step = 6
    const delay = 18
    let cur = 0
    const id = setInterval(() => {
      cur += step
      setShown(cur)
      if (cur >= fullText.length) clearInterval(id)
    }, delay)
    return () => clearInterval(id)
  }, [fullText])

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [shown])

  if (!fullText) {
    return (
      <div className="reasoning-viewer" style={{ opacity: 0.5, minHeight: 80 }}>
        <span className="line-agent">— awaiting agent reasoning —</span>
      </div>
    )
  }

  const visible = fullText.slice(0, shown)
  const lines   = visible.split('\n')
  const isTyping = shown < fullText.length

  return (
    <div className="reasoning-viewer" ref={ref}>
      {lines.map((line, i) => (
        <div key={i}>{colourLine(line)}</div>
      ))}
      {isTyping && <span className="reasoning-typing" />}
    </div>
  )
}

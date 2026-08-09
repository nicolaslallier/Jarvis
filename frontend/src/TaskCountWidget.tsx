import { useEffect, useState } from 'react'

type CountData = { total: number; done: number; active: number }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function TaskCountWidget() {
  const [state, setState] = useState<{ phase: 'loading' } | { phase: 'ok'; data: CountData }>(
    { phase: 'loading' },
  )

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/tasks/count`)
        if (cancelled) return
        if (res.ok) {
          const data: CountData = await res.json()
          setState({ phase: 'ok', data })
        }
      } catch {
        // silently fail — not critical
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="task-count">
      {state.phase === 'loading' && <span className="task-count-loading">Loading…</span>}
      {state.phase === 'ok' && (
        <>
          <span className="task-count-total">{state.data.total} tasks</span>
          {state.data.active > 0 && (
            <span className="task-count-active">{state.data.active} active</span>
          )}
          {state.data.done > 0 && (
            <span className="task-count-done">{state.data.done} done</span>
          )}
        </>
      )}
    </section>
  )
}

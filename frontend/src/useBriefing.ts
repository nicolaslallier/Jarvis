import { useEffect, useState } from 'react'
import type { Appointment } from './useCalendar'
import type { Task } from './useTasks'

export type Briefing = {
  date: string
  appointments: Appointment[]
  due_tasks: Task[]
  overdue_tasks: Task[]
  summary: string | null
}

type BriefingState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Briefing }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useBriefing() {
  const [state, setState] = useState<BriefingState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/briefing`)
        if (cancelled) return

        if (res.ok) {
          const data: Briefing = await res.json()
          setState({ phase: 'ok', data })
        } else {
          setState({ phase: 'error', message: await errorMessage(res) })
        }
      } catch (err) {
        if (cancelled) return
        setState({
          phase: 'error',
          message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
        })
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  return { state }
}

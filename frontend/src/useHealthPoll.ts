import { useEffect, useState } from 'react'

type HealthOk = { status: string; database: string }

type PollState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: HealthOk; lastChecked: Date }
  | { phase: 'error'; message: string; lastChecked: Date }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const POLL_INTERVAL_MS = 5000

export function useHealthPoll(): PollState {
  const [state, setState] = useState<PollState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function poll() {
      try {
        const res = await fetch(`${API_URL}/health`)
        if (cancelled) return

        if (res.ok) {
          const data: HealthOk = await res.json()
          setState({ phase: 'ok', data, lastChecked: new Date() })
        } else {
          const body = await res.json().catch(() => null)
          setState({
            phase: 'error',
            message: body?.detail ?? `Backend returned ${res.status}`,
            lastChecked: new Date(),
          })
        }
      } catch (err) {
        if (cancelled) return
        setState({
          phase: 'error',
          message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
          lastChecked: new Date(),
        })
      }
    }

    poll()
    const id = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  return state
}

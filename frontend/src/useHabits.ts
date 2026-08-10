import { useEffect, useState } from 'react'

export type HabitFrequency = 'daily' | 'weekly'

export type Habit = {
  id: number
  name: string
  frequency: string
  streak_count: number
  last_completed_at: string | null
  created_at: string
}

type HabitsState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Habit[] }
  | { phase: 'error'; message: string }

export type NewHabit = {
  name: string
  frequency: HabitFrequency
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useHabits() {
  const [state, setState] = useState<HabitsState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/habits`)
        if (cancelled) return

        if (res.ok) {
          const data: Habit[] = await res.json()
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

  async function createHabit(input: NewHabit): Promise<void> {
    const res = await fetch(`${API_URL}/habits`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Habit = await res.json()
    setState((prev) => (prev.phase === 'ok' ? { phase: 'ok', data: [...prev.data, created] } : prev))
  }

  async function completeHabit(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/habits/${id}/complete`, { method: 'POST' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Habit = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: prev.data.map((h) => (h.id === updated.id ? updated : h)) }
        : prev,
    )
  }

  async function deleteHabit(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/habits/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) => (prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((h) => h.id !== id) } : prev))
  }

  return { state, createHabit, completeHabit, deleteHabit }
}

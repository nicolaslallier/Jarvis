import { useEffect, useState } from 'react'

export type Appointment = {
  id: number
  title: string
  description: string | null
  location: string | null
  start_time: string
  end_time: string
  all_day: boolean
  created_at: string
  updated_at: string
}

type AppointmentsState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Appointment[] }
  | { phase: 'error'; message: string }

type NewAppointment = {
  title: string
  start_time: string
  end_time: string
  description?: string
  location?: string
  all_day?: boolean
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function sortByStartTime(appointments: Appointment[]): Appointment[] {
  return [...appointments].sort((a, b) => a.start_time.localeCompare(b.start_time))
}

export function useCalendar() {
  const [state, setState] = useState<AppointmentsState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/calendar/appointments`)
        if (cancelled) return

        if (res.ok) {
          const data: Appointment[] = await res.json()
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

  async function createAppointment(input: NewAppointment): Promise<void> {
    const res = await fetch(`${API_URL}/calendar/appointments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Appointment = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: sortByStartTime([...prev.data, created]) } : prev,
    )
  }

  async function updateAppointment(id: number, input: NewAppointment): Promise<void> {
    const res = await fetch(`${API_URL}/calendar/appointments/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Appointment = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: sortByStartTime(prev.data.map((a) => (a.id === updated.id ? updated : a))) }
        : prev,
    )
  }

  async function deleteAppointment(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/calendar/appointments/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((a) => a.id !== id) } : prev,
    )
  }

  return { state, createAppointment, updateAppointment, deleteAppointment }
}

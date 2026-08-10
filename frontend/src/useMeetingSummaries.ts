import { useEffect, useState } from 'react'

export type MeetingSummary = {
  id: number
  title: string
  meeting_date: string
  participants: string | null
  content: string
  appointment_id: number | null
  created_at: string
  updated_at: string
}

type MeetingSummariesState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: MeetingSummary[] }
  | { phase: 'error'; message: string }

export type NewMeetingSummary = {
  title: string
  meeting_date: string
  content: string
  participants?: string | null
  appointment_id?: number | null
}

export type MeetingSummaryUpdateInput = Partial<NewMeetingSummary>

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function sortByMeetingDateDesc(summaries: MeetingSummary[]): MeetingSummary[] {
  return [...summaries].sort((a, b) => b.meeting_date.localeCompare(a.meeting_date))
}

export function useMeetingSummaries() {
  const [state, setState] = useState<MeetingSummariesState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/meeting-summaries`)
        if (cancelled) return

        if (res.ok) {
          const data: MeetingSummary[] = await res.json()
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

  async function createMeetingSummary(input: NewMeetingSummary): Promise<void> {
    const res = await fetch(`${API_URL}/meeting-summaries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: MeetingSummary = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: sortByMeetingDateDesc([...prev.data, created]) } : prev,
    )
  }

  async function updateMeetingSummary(id: number, input: MeetingSummaryUpdateInput): Promise<void> {
    const res = await fetch(`${API_URL}/meeting-summaries/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: MeetingSummary = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? {
            phase: 'ok',
            data: sortByMeetingDateDesc(prev.data.map((m) => (m.id === updated.id ? updated : m))),
          }
        : prev,
    )
  }

  async function deleteMeetingSummary(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/meeting-summaries/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((m) => m.id !== id) } : prev,
    )
  }

  return { state, createMeetingSummary, updateMeetingSummary, deleteMeetingSummary }
}

import { useEffect, useState } from 'react'

export type TaskStatus = 'todo' | 'doing' | 'done' | 'cancelled'
export type TaskPriority = 'low' | 'normal' | 'high'

export type Task = {
  id: number
  title: string
  description: string | null
  due_at: string | null
  status: TaskStatus
  priority: TaskPriority
  completed_at: string | null
  project: string | null
  tags: string[] | null
  parent_id: number | null
  recurrence_rule: string | null
  appointment_id: number | null
  file_id: number | null
  created_at: string
}

type TasksState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Task[] }
  | { phase: 'error'; message: string }

export type NewTask = {
  title: string
  description?: string
  due_at?: string
  priority?: TaskPriority
  project?: string
  tags?: string[]
  parent_id?: number
}

// Unlike NewTask, every field here that can be cleared accepts an explicit
// `null` — and JSON.stringify keeps null keys but drops undefined ones, so
// callers must pass null (not omit the field) to actually clear a value.
export type TaskUpdateInput = Partial<{
  title: string
  description: string | null
  due_at: string | null
  status: TaskStatus
  priority: TaskPriority
  project: string | null
  tags: string[] | null
  parent_id: number | null
}>

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useTasks() {
  const [state, setState] = useState<TasksState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/tasks`)
        if (cancelled) return

        if (res.ok) {
          const data: Task[] = await res.json()
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

  async function createTask(input: NewTask): Promise<void> {
    const res = await fetch(`${API_URL}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Task = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: [...prev.data, created] } : prev,
    )
  }

  async function completeTask(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/tasks/${id}/complete`, { method: 'POST' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Task = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: prev.data.map((t) => (t.id === updated.id ? updated : t)) }
        : prev,
    )
  }

  async function deleteTask(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/tasks/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((t) => t.id !== id) } : prev,
    )
  }

  async function updateTask(id: number, input: TaskUpdateInput): Promise<void> {
    const res = await fetch(`${API_URL}/tasks/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Task = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: prev.data.map((t) => (t.id === updated.id ? updated : t)) }
        : prev,
    )
  }

  return { state, createTask, completeTask, deleteTask, updateTask }
}

import { useEffect, useState } from 'react'

export type Memory = {
  id: number
  content: string
  session_id: number | null
  created_at: string
}

type MemoriesState =
  | { phase: 'loading' }
  | { phase: 'ok'; memories: Memory[] }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useMemories() {
  const [state, setState] = useState<MemoriesState>({ phase: 'loading' })

  async function load(): Promise<void> {
    setState({ phase: 'loading' })
    try {
      const res = await fetch(`${API_URL}/memories`)
      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }
      const memories: Memory[] = await res.json()
      setState({ phase: 'ok', memories })
    } catch (err) {
      setState({
        phase: 'error',
        message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function updateMemory(id: number, content: string): Promise<void> {
    const res = await fetch(`${API_URL}/memories/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Memory = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { ...prev, memories: prev.memories.map((m) => (m.id === id ? updated : m)) }
        : prev,
    )
  }

  async function deleteMemory(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/memories/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { ...prev, memories: prev.memories.filter((m) => m.id !== id) } : prev,
    )
  }

  return { state, updateMemory, deleteMemory }
}

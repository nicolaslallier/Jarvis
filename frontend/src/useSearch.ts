import { useState } from 'react'

export type SearchResultKind = 'task' | 'appointment' | 'file_chunk' | 'memory' | 'chat_message'

export type SearchResult = {
  kind: SearchResultKind
  id: number
  title: string
  snippet: string
  // null for ILIKE-based kinds (task/appointment/chat_message); the raw
  // cosine distance (lower = closer) for vector-based kinds (file_chunk/
  // memory) — see backend/app/search_service.py. Never a unified score
  // across kinds.
  score: number | null
}

export type SearchResponse = {
  query: string
  results: SearchResult[]
}

type SearchState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'ok'; data: SearchResponse }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

// Fires on demand (form submit), not live-as-you-type — each search is a
// deliberate action, not a keystroke-driven request.
export function useSearch() {
  const [state, setState] = useState<SearchState>({ phase: 'idle' })

  async function runSearch(query: string): Promise<void> {
    const trimmed = query.trim()
    if (!trimmed) return

    setState({ phase: 'loading' })
    try {
      const res = await fetch(`${API_URL}/search?q=${encodeURIComponent(trimmed)}`)
      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }
      const data: SearchResponse = await res.json()
      setState({ phase: 'ok', data })
    } catch (err) {
      setState({
        phase: 'error',
        message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  return { state, runSearch }
}

import { useEffect, useState } from 'react'

export type ChatMessage = {
  id: number
  role: 'system' | 'user' | 'assistant'
  content: string
  created_at: string
}

export type ChatSession = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

type SessionsState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: ChatSession[] }
  | { phase: 'error'; message: string }

type MessagesState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'sending' }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function networkErrorMessage(err: unknown): string {
  return `Network error: ${err instanceof Error ? err.message : String(err)}`
}

function sortByMostRecentlyActive(sessions: ChatSession[]): ChatSession[] {
  return [...sessions].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )
}

export function useChat() {
  const [sessions, setSessions] = useState<SessionsState>({ phase: 'loading' })
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [state, setState] = useState<MessagesState>({ phase: 'idle' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/chat/sessions`)
        if (cancelled) return

        if (!res.ok) {
          setSessions({ phase: 'error', message: await errorMessage(res) })
          return
        }

        const data: ChatSession[] = await res.json()
        setSessions({ phase: 'ok', data })
        if (data.length > 0) {
          await selectSession(data[0].id)
        }
      } catch (err) {
        if (cancelled) return
        setSessions({ phase: 'error', message: networkErrorMessage(err) })
      }
    }

    load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function selectSession(id: number): Promise<void> {
    setActiveSessionId(id)
    setState({ phase: 'loading' })

    try {
      const res = await fetch(`${API_URL}/chat/sessions/${id}`)
      if (!res.ok) {
        setMessages([])
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }

      const data: ChatSession & { messages: ChatMessage[] } = await res.json()
      setMessages(data.messages)
      setState({ phase: 'idle' })
    } catch (err) {
      setMessages([])
      setState({ phase: 'error', message: networkErrorMessage(err) })
    }
  }

  async function createSession(): Promise<void> {
    try {
      const res = await fetch(`${API_URL}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }

      const created: ChatSession = await res.json()
      setSessions((prev) =>
        prev.phase === 'ok'
          ? { phase: 'ok', data: sortByMostRecentlyActive([created, ...prev.data]) }
          : { phase: 'ok', data: [created] },
      )
      setActiveSessionId(created.id)
      setMessages([])
      setState({ phase: 'idle' })
    } catch (err) {
      setState({ phase: 'error', message: networkErrorMessage(err) })
    }
  }

  async function deleteSession(id: number): Promise<void> {
    try {
      const res = await fetch(`${API_URL}/chat/sessions/${id}`, { method: 'DELETE' })
      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }

      setSessions((prev) =>
        prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((s) => s.id !== id) } : prev,
      )
      if (activeSessionId === id) {
        setActiveSessionId(null)
        setMessages([])
        setState({ phase: 'idle' })
      }
    } catch (err) {
      setState({ phase: 'error', message: networkErrorMessage(err) })
    }
  }

  async function sendMessage(content: string): Promise<void> {
    let sessionId = activeSessionId

    if (sessionId === null) {
      const res = await fetch(`${API_URL}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      }).catch((err) => {
        setState({ phase: 'error', message: networkErrorMessage(err) })
        return null
      })
      if (!res) return
      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }
      const created: ChatSession = await res.json()
      sessionId = created.id
      setActiveSessionId(created.id)
      setSessions((prev) =>
        prev.phase === 'ok'
          ? { phase: 'ok', data: sortByMostRecentlyActive([created, ...prev.data]) }
          : { phase: 'ok', data: [created] },
      )
    }

    const optimisticUser: ChatMessage = {
      id: -Date.now(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, optimisticUser])
    setState({ phase: 'sending' })

    try {
      const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })

      if (!res.ok) {
        const message = await errorMessage(res)
        // The user message may already be persisted server-side even though
        // the LM Studio call failed — reload from the server so the UI
        // reflects what's actually saved instead of a stale optimistic entry.
        await selectSession(sessionId)
        setState({ phase: 'error', message })
        return
      }

      const data: { session: ChatSession; user_message: ChatMessage; assistant_message: ChatMessage } =
        await res.json()
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== optimisticUser.id),
        data.user_message,
        data.assistant_message,
      ])
      setSessions((prev) =>
        prev.phase === 'ok'
          ? {
              phase: 'ok',
              data: sortByMostRecentlyActive([
                data.session,
                ...prev.data.filter((s) => s.id !== data.session.id),
              ]),
            }
          : prev,
      )
      setState({ phase: 'idle' })
    } catch (err) {
      setState({ phase: 'error', message: networkErrorMessage(err) })
    }
  }

  return {
    sessions,
    activeSessionId,
    messages,
    state,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
  }
}

import { useEffect, useRef, useState } from 'react'

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

// Server-sent events the streaming POST /chat/sessions/{id}/messages
// endpoint emits, in the order they can arrive (see
// backend/app/routers/chat.py's _stream_send_message).
type ChatStreamEvent =
  | { type: 'user_message'; message: ChatMessage }
  | { type: 'session'; session: ChatSession }
  | { type: 'delta'; content: string }
  | { type: 'tool_call'; name: string }
  | { type: 'done'; assistant_message: ChatMessage; session: ChatSession }
  | { type: 'error'; detail: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// Sentinel id for the assistant message being streamed in, before it has a
// real database id — negative like the optimistic user-message id below so
// neither can collide with a real (positive) message id.
const STREAMING_ASSISTANT_ID = -1

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

async function* readSseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatStreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let separatorIndex: number
    while ((separatorIndex = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, separatorIndex)
      buffer = buffer.slice(separatorIndex + 2)
      if (!block.startsWith('data:')) continue
      yield JSON.parse(block.slice('data:'.length).trim()) as ChatStreamEvent
    }
  }
}

export function useChat() {
  const [sessions, setSessions] = useState<SessionsState>({ phase: 'loading' })
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [state, setState] = useState<MessagesState>({ phase: 'idle' })
  const [toolActivity, setToolActivity] = useState<string | null>(null)
  const lastFailedMessage = useRef<string | null>(null)

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
    setToolActivity(null)

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
    setToolActivity(null)

    try {
      const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })

      if (!res.ok || !res.body) {
        const message = res.ok ? 'Empty response body' : await errorMessage(res)
        // The user message may already be persisted server-side even though
        // the send failed — reload from the server so the UI reflects
        // what's actually saved instead of a stale optimistic entry.
        await selectSession(sessionId)
        lastFailedMessage.current = content
        setState({ phase: 'error', message })
        return
      }

      let streamedContent = ''
      let sawAssistantPlaceholder = false
      let streamError: string | null = null

      for await (const event of readSseEvents(res.body)) {
        if (event.type === 'user_message') {
          setMessages((prev) => [...prev.filter((m) => m.id !== optimisticUser.id), event.message])
        } else if (event.type === 'session') {
          setSessions((prev) =>
            prev.phase === 'ok'
              ? {
                  phase: 'ok',
                  data: sortByMostRecentlyActive([
                    event.session,
                    ...prev.data.filter((s) => s.id !== event.session.id),
                  ]),
                }
              : prev,
          )
        } else if (event.type === 'delta') {
          streamedContent += event.content
          setToolActivity(null)
          if (!sawAssistantPlaceholder) {
            sawAssistantPlaceholder = true
            const placeholder: ChatMessage = {
              id: STREAMING_ASSISTANT_ID,
              role: 'assistant',
              content: streamedContent,
              created_at: new Date().toISOString(),
            }
            setMessages((prev) => [...prev, placeholder])
          } else {
            setMessages((prev) =>
              prev.map((m) => (m.id === STREAMING_ASSISTANT_ID ? { ...m, content: streamedContent } : m)),
            )
          }
        } else if (event.type === 'tool_call') {
          setToolActivity(event.name)
        } else if (event.type === 'error') {
          streamError = event.detail
        } else if (event.type === 'done') {
          setMessages((prev) => [
            ...prev.filter((m) => m.id !== STREAMING_ASSISTANT_ID),
            event.assistant_message,
          ])
          setToolActivity(null)
        }
      }

      if (streamError) {
        lastFailedMessage.current = content
        setState({ phase: 'error', message: streamError })
        return
      }

      lastFailedMessage.current = null
      setState({ phase: 'idle' })
    } catch (err) {
      lastFailedMessage.current = content
      setState({ phase: 'error', message: networkErrorMessage(err) })
    }
  }

  async function retryLastMessage(): Promise<void> {
    const content = lastFailedMessage.current
    if (!content) return
    await sendMessage(content)
  }

  return {
    sessions,
    activeSessionId,
    messages,
    state,
    toolActivity,
    canRetry: lastFailedMessage.current !== null,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
    retryLastMessage,
  }
}

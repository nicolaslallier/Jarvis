import { useState } from 'react'

export type ChatMessage = {
  role: 'system' | 'user' | 'assistant'
  content: string
}

type ChatState =
  | { phase: 'idle' }
  | { phase: 'sending' }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [state, setState] = useState<ChatState>({ phase: 'idle' })

  async function sendMessage(content: string): Promise<void> {
    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content }]
    setMessages(nextMessages)
    setState({ phase: 'sending' })

    try {
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: nextMessages }),
      })

      if (!res.ok) {
        setState({ phase: 'error', message: await errorMessage(res) })
        return
      }

      const data: { message: ChatMessage } = await res.json()
      setMessages([...nextMessages, data.message])
      setState({ phase: 'idle' })
    } catch (err) {
      setState({
        phase: 'error',
        message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  return { messages, state, sendMessage }
}

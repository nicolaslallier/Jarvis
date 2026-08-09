import { useState } from 'react'
import type { FormEvent } from 'react'
import { useChat } from './useChat'

export default function ChatPage() {
  const { messages, state, sendMessage } = useChat()
  const [input, setInput] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || state.phase === 'sending') return
    const content = input
    setInput('')
    await sendMessage(content)
  }

  return (
    <div className="chat">
      <h1>Chat</h1>

      <ul className="chat-messages">
        {messages.length === 0 && (
          <li className="chat-empty">Say hello to your LM Studio model.</li>
        )}
        {messages.map((m, i) => (
          <li key={i} className={`chat-message chat-message-${m.role}`}>
            <span className="chat-message-role">{m.role}</span>
            <p className="chat-message-content">{m.content}</p>
          </li>
        ))}
        {state.phase === 'sending' && (
          <li className="chat-message chat-message-assistant chat-message-pending">
            <span className="chat-message-role">assistant</span>
            <p className="chat-message-content">Thinking…</p>
          </li>
        )}
      </ul>

      {state.phase === 'error' && <p className="chat-error">{state.message}</p>}

      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Type a message…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={state.phase === 'sending'}
        />
        <button type="submit" disabled={state.phase === 'sending' || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}

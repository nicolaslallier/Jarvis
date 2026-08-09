import { useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'
import { useChat } from './useChat'

export default function ChatPage() {
  const {
    sessions,
    activeSessionId,
    messages,
    state,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
  } = useChat()
  const [input, setInput] = useState('')

  const busy = state.phase === 'sending' || state.phase === 'loading'

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || busy) return
    const content = input
    setInput('')
    await sendMessage(content)
  }

  async function handleDelete(e: MouseEvent, id: number) {
    e.stopPropagation()
    await deleteSession(id)
  }

  return (
    <div className="chat">
      <h1>Chat</h1>

      <div className="chat-sessions">
        <button type="button" className="chat-session-new" onClick={() => createSession()}>
          + New chat
        </button>
        {sessions.phase === 'ok' &&
          sessions.data.map((s) => (
            <button
              key={s.id}
              type="button"
              className={
                s.id === activeSessionId ? 'chat-session chat-session-active' : 'chat-session'
              }
              onClick={() => selectSession(s.id)}
            >
              <span className="chat-session-title">{s.title}</span>
              <span
                className="chat-session-delete"
                role="button"
                aria-label={`Delete ${s.title}`}
                onClick={(e) => handleDelete(e, s.id)}
              >
                ×
              </span>
            </button>
          ))}
        {sessions.phase === 'error' && (
          <span className="chat-error">Could not load chats: {sessions.message}</span>
        )}
      </div>

      <ul className="chat-messages">
        {messages.length === 0 && (
          <li className="chat-empty">Say hello to your LM Studio model.</li>
        )}
        {messages.map((m) => (
          <li key={m.id} className={`chat-message chat-message-${m.role}`}>
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
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}

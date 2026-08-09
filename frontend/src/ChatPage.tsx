import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChat } from './useChat'

const TEXTAREA_MAX_HEIGHT_PX = 160

function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
}

export default function ChatPage() {
  const {
    sessions,
    activeSessionId,
    messages,
    state,
    toolActivity,
    canRetry,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
    retryLastMessage,
  } = useChat()
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLLIElement>(null)

  const busy = state.phase === 'sending' || state.phase === 'loading'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, toolActivity])

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, TEXTAREA_MAX_HEIGHT_PX)}px`
  }, [input])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || busy) return
    const content = input
    setInput('')
    await sendMessage(content)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      e.currentTarget.form?.requestSubmit()
    }
  }

  async function handleDelete(id: number, title: string) {
    if (!window.confirm(`Delete "${title}"? This can't be undone.`)) return
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
            <div
              key={s.id}
              className={
                s.id === activeSessionId ? 'chat-session chat-session-active' : 'chat-session'
              }
            >
              <button
                type="button"
                className="chat-session-select"
                onClick={() => selectSession(s.id)}
              >
                <span className="chat-session-title">{s.title}</span>
              </button>
              <button
                type="button"
                className="chat-session-delete"
                aria-label={`Delete ${s.title}`}
                onClick={() => handleDelete(s.id, s.title)}
              >
                ×
              </button>
            </div>
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
          <li
            key={m.id}
            className={`chat-message chat-message-${m.role}`}
            title={formatTimestamp(m.created_at)}
          >
            <span className="chat-message-role">{m.role}</span>
            <div className="chat-message-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content || '…'}</ReactMarkdown>
            </div>
          </li>
        ))}
        {toolActivity && (
          <li className="chat-message chat-message-assistant chat-message-pending">
            <span className="chat-message-role">assistant</span>
            <p className="chat-tool-activity">Using {toolActivity}…</p>
          </li>
        )}
        <li ref={bottomRef} className="chat-messages-end" aria-hidden="true" />
      </ul>

      {state.phase === 'error' && (
        <p className="chat-error">
          {state.message}
          {canRetry && (
            <button type="button" className="chat-retry" onClick={() => retryLastMessage()}>
              Retry
            </button>
          )}
        </p>
      )}

      <form className="chat-form" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}

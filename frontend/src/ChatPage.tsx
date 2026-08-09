import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChat } from './useChat'

const TEXTAREA_MAX_HEIGHT_PX = 160
// How long the "Copié" confirmation stays visible after clicking a
// message's copy button, in milliseconds.
const COPY_FEEDBACK_MS = 1500

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
    stopGeneration,
    retryLastMessage,
  } = useChat()
  const [input, setInput] = useState('')
  const [sessionFilter, setSessionFilter] = useState('')
  const [copiedMessageId, setCopiedMessageId] = useState<number | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLLIElement>(null)

  const busy = state.phase === 'sending' || state.phase === 'loading'
  const isStreaming = state.phase === 'sending'

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
    if (!window.confirm(`Supprimer « ${title} » ? Cette action est irréversible.`)) return
    await deleteSession(id)
  }

  async function handleCopy(id: number, content: string) {
    try {
      await navigator.clipboard.writeText(content)
      setCopiedMessageId(id)
      setTimeout(() => setCopiedMessageId((current) => (current === id ? null : current)), COPY_FEEDBACK_MS)
    } catch {
      // Clipboard access can fail (permissions, insecure context) — silently
      // no-op rather than surfacing a chat-level error for a non-critical
      // convenience action.
    }
  }

  const filteredSessions =
    sessions.phase === 'ok'
      ? sessions.data.filter((s) => s.title.toLowerCase().includes(sessionFilter.trim().toLowerCase()))
      : []

  return (
    <div className="chat">
      <h1>Chat</h1>

      <input
        type="text"
        className="chat-session-search"
        placeholder="Rechercher une conversation…"
        value={sessionFilter}
        onChange={(e) => setSessionFilter(e.target.value)}
        aria-label="Rechercher une conversation"
      />

      <div className="chat-sessions">
        <button type="button" className="chat-session-new" onClick={() => createSession()}>
          + Nouvelle conversation
        </button>
        {sessions.phase === 'ok' &&
          filteredSessions.map((s) => (
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
                aria-label={`Supprimer ${s.title}`}
                onClick={() => handleDelete(s.id, s.title)}
              >
                ×
              </button>
            </div>
          ))}
        {sessions.phase === 'error' && (
          <span className="chat-error">Impossible de charger les conversations : {sessions.message}</span>
        )}
      </div>

      <ul className="chat-messages">
        {messages.length === 0 && (
          <li className="chat-empty">Dites bonjour à votre modèle LM Studio.</li>
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
            {m.sources && m.sources.length > 0 && (
              <div className="chat-message-sources">
                <span className="chat-message-sources-label">Sources utilisées :</span>
                <ul>
                  {m.sources.map((source, i) => (
                    <li key={`${source.filename}-${source.chunk_index}-${i}`}>
                      <span className="chat-message-source-filename">{source.filename}</span>
                      {` (extrait ${source.chunk_index}) — `}
                      <span className="chat-message-source-excerpt">{source.excerpt}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <button
              type="button"
              className="chat-message-copy"
              onClick={() => handleCopy(m.id, m.content)}
            >
              {copiedMessageId === m.id ? 'Copié' : 'Copier'}
            </button>
          </li>
        ))}
        {toolActivity && (
          <li className="chat-message chat-message-assistant chat-message-pending">
            <span className="chat-message-role">assistant</span>
            <p className="chat-tool-activity">Utilisation de {toolActivity}…</p>
          </li>
        )}
        <li ref={bottomRef} className="chat-messages-end" aria-hidden="true" />
      </ul>

      {state.phase === 'error' && (
        <p className="chat-error">
          {state.message}
          {canRetry && (
            <button type="button" className="chat-retry" onClick={() => retryLastMessage()}>
              Réessayer
            </button>
          )}
        </p>
      )}

      <form className="chat-form" onSubmit={handleSubmit}>
        <textarea
          ref={textareaRef}
          placeholder="Écrivez un message… (Entrée pour envoyer, Maj+Entrée pour un saut de ligne)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
        />
        {isStreaming ? (
          <button type="button" className="chat-stop" onClick={() => stopGeneration()}>
            Arrêter
          </button>
        ) : (
          <button type="submit" disabled={busy || !input.trim()}>
            Envoyer
          </button>
        )}
      </form>
    </div>
  )
}

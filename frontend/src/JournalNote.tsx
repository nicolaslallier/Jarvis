import { useState } from 'react'
import type { FormEvent } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

type Status = { phase: 'idle' } | { phase: 'saving' } | { phase: 'success' } | { phase: 'error'; message: string }

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Le serveur a répondu ${res.status}`
}

// Self-contained textarea + submit button that saves a quick journal note
// as a Memory (source='journal', see backend/app/routers/memory.py's POST
// /memories), so it's retrieved by chat like any other remembered fact.
// Deliberately not a page/route of its own — meant to be embedded into a
// larger composition (e.g. a Today page) by whatever renders it.
export default function JournalNote() {
  const [content, setContent] = useState('')
  const [status, setStatus] = useState<Status>({ phase: 'idle' })

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = content.trim()
    if (!trimmed) return

    setStatus({ phase: 'saving' })
    try {
      const res = await fetch(`${API_URL}/memories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: trimmed }),
      })
      if (!res.ok) {
        setStatus({ phase: 'error', message: await errorMessage(res) })
        return
      }
      setContent('')
      setStatus({ phase: 'success' })
    } catch (err) {
      setStatus({
        phase: 'error',
        message: `Erreur réseau : ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  const saving = status.phase === 'saving'

  return (
    <section className="journal-note">
      <form className="journal-note-form" onSubmit={handleSubmit}>
        <textarea
          className="journal-note-textarea"
          value={content}
          onChange={(e) => {
            setContent(e.target.value)
            if (status.phase !== 'idle') setStatus({ phase: 'idle' })
          }}
          placeholder="Notez une pensée, un fait à retenir…"
          disabled={saving}
          rows={3}
        />
        <div className="journal-note-actions">
          <button type="submit" disabled={saving || !content.trim()}>
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
          {status.phase === 'success' && <span className="journal-note-success">Enregistré ✓</span>}
          {status.phase === 'error' && <span className="journal-note-error">{status.message}</span>}
        </div>
      </form>
    </section>
  )
}

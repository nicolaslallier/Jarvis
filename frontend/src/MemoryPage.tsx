import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMemories } from './useMemories'
import type { Memory } from './useMemories'

function formatTimestamp(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('fr-FR')
}

export default function MemoryPage() {
  const { state, updateMemory, deleteMemory } = useMemories()

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editContent, setEditContent] = useState('')
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [pendingIds, setPendingIds] = useState<Set<number>>(new Set())

  function runRowAction(id: number, action: () => Promise<void>) {
    setRowErrors((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setPendingIds((prev) => new Set(prev).add(id))
    action()
      .catch((err) => {
        setRowErrors((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : String(err) }))
      })
      .finally(() => {
        setPendingIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      })
  }

  function startEdit(memory: Memory) {
    setEditingId(memory.id)
    setEditContent(memory.content)
  }

  function cancelEdit() {
    setEditingId(null)
    setEditContent('')
  }

  function handleSave(e: FormEvent, id: number) {
    e.preventDefault()
    const content = editContent.trim()
    if (!content) return
    runRowAction(id, async () => {
      await updateMemory(id, content)
      setEditingId(null)
      setEditContent('')
    })
  }

  function handleDelete(memory: Memory) {
    if (!window.confirm('Supprimer ce souvenir ? Cette action est définitive.')) return
    runRowAction(memory.id, () => deleteMemory(memory.id))
  }

  function renderMemory(memory: Memory) {
    const pending = pendingIds.has(memory.id)

    if (editingId === memory.id) {
      return (
        <li key={memory.id} className="memory-item">
          <form className="memory-edit-form" onSubmit={(e) => handleSave(e, memory.id)}>
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              required
              disabled={pending}
              className="memory-edit-textarea"
            />
            <div className="memory-edit-actions">
              <button type="submit" disabled={pending || !editContent.trim()}>
                {pending ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" onClick={cancelEdit} disabled={pending}>
                Annuler
              </button>
            </div>
            {rowErrors[memory.id] && <p className="memory-row-error">{rowErrors[memory.id]}</p>}
          </form>
        </li>
      )
    }

    return (
      <li key={memory.id} className="memory-item">
        <p className="memory-content">{memory.content}</p>
        <div className="memory-item-meta">
          <span className="memory-created-at">Appris le {formatTimestamp(memory.created_at)}</span>
        </div>
        <div className="memory-item-actions">
          <button type="button" onClick={() => startEdit(memory)} className="memory-edit-btn" disabled={pending}>
            Modifier
          </button>
          <button type="button" onClick={() => handleDelete(memory)} className="memory-delete" disabled={pending}>
            {pending ? '…' : 'Supprimer'}
          </button>
        </div>
        {rowErrors[memory.id] && <p className="memory-row-error">{rowErrors[memory.id]}</p>}
      </li>
    )
  }

  return (
    <div className="memory-page">
      <h1>Mémoire</h1>

      {state.phase === 'loading' && <p className="memory-loading">Chargement des souvenirs…</p>}
      {state.phase === 'error' && <p className="memory-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {state.memories.length === 0 && (
            <p className="memory-empty">Aucun souvenir enregistré pour l'instant.</p>
          )}
          {state.memories.length > 0 && (
            <ul className="memory-list">{state.memories.map(renderMemory)}</ul>
          )}
        </>
      )}
    </div>
  )
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useHabits } from './useHabits'
import type { Habit, HabitFrequency } from './useHabits'

// Self-contained page: styling lives in this file (not App.css) so this
// component has no dependency on the nav-wiring task that adds it to
// App.tsx/App.css.
const STYLES = `
.habits-page { max-width: 640px; margin: 0 auto; }
.habits-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}
.habits-form input[type="text"] {
  flex: 1 1 12rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #ccc);
}
.habits-form select {
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #ccc);
}
.habits-form button {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  border: none;
  background: #4f46e5;
  color: #fff;
  cursor: pointer;
}
.habits-form button:disabled { opacity: 0.6; cursor: default; }
.habits-form-error { color: #dc2626; width: 100%; margin: 0; }
.habits-loading, .habits-empty { opacity: 0.7; }
.habits-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.habit-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--border-color, #ddd);
}
.habit-item-main {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}
.habit-name { font-weight: 600; }
.habit-frequency-badge {
  font-size: 0.75rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: rgba(79, 70, 229, 0.12);
  color: #4f46e5;
}
.habit-streak {
  font-size: 0.9rem;
  white-space: nowrap;
}
.habit-delete {
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
}
.habit-delete:disabled { opacity: 0.5; cursor: default; }
.habit-row-error { color: #dc2626; margin: 0.25rem 0 0 0; font-size: 0.85rem; }
`

const FREQUENCY_LABELS: Record<HabitFrequency, string> = {
  daily: 'Quotidien',
  weekly: 'Hebdomadaire',
}

function isDoneForWindow(habit: Habit): boolean {
  if (!habit.last_completed_at) return false
  const gapMs = Date.now() - new Date(habit.last_completed_at).getTime()
  // Mirrors the backend's grace windows (habit_service.py's
  // _STREAK_WINDOWS) closely enough to decide whether "done today/this
  // week" should already be checked, without duplicating exact logic.
  const windowMs = habit.frequency === 'weekly' ? 9 * 86_400_000 : 2 * 86_400_000
  return gapMs <= windowMs
}

function defaultCreateForm() {
  return { name: '', frequency: 'daily' as HabitFrequency }
}

export default function HabitsPage() {
  const { state, createHabit, completeHabit, deleteHabit } = useHabits()

  const [form, setForm] = useState(defaultCreateForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

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

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    const name = form.name.trim()
    if (!name) return
    setCreating(true)
    try {
      await createHabit({ name, frequency: form.frequency })
      setForm(defaultCreateForm())
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function handleMarkDone(habit: Habit) {
    if (pendingIds.has(habit.id) || isDoneForWindow(habit)) return
    runRowAction(habit.id, () => completeHabit(habit.id))
  }

  function handleDelete(habit: Habit) {
    if (!window.confirm(`Supprimer l'habitude « ${habit.name} » ? Cette action est définitive.`)) return
    runRowAction(habit.id, () => deleteHabit(habit.id))
  }

  function renderHabit(habit: Habit) {
    const pending = pendingIds.has(habit.id)
    const done = isDoneForWindow(habit)

    return (
      <li key={habit.id} className="habit-item">
        <label className="habit-item-main">
          <input
            type="checkbox"
            checked={done}
            disabled={pending || done}
            onChange={() => handleMarkDone(habit)}
          />
          <span className="habit-name">{habit.name}</span>
          <span className="habit-frequency-badge">{FREQUENCY_LABELS[habit.frequency as HabitFrequency] ?? habit.frequency}</span>
        </label>
        <span className="habit-streak">🔥 {habit.streak_count}</span>
        <button type="button" className="habit-delete" onClick={() => handleDelete(habit)} disabled={pending}>
          {pending ? '…' : 'Supprimer'}
        </button>
        {rowErrors[habit.id] && <p className="habit-row-error">{rowErrors[habit.id]}</p>}
      </li>
    )
  }

  return (
    <div className="habits-page">
      <style>{STYLES}</style>
      <h1>Habitudes</h1>

      <form className="habits-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Nom de l'habitude"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <select
          value={form.frequency}
          onChange={(e) => setForm({ ...form, frequency: e.target.value as HabitFrequency })}
        >
          {(Object.keys(FREQUENCY_LABELS) as HabitFrequency[]).map((f) => (
            <option key={f} value={f}>
              {FREQUENCY_LABELS[f]}
            </option>
          ))}
        </select>
        <button type="submit" disabled={creating || !form.name.trim()}>
          {creating ? 'Ajout…' : 'Ajouter'}
        </button>
        {formError && <p className="habits-form-error">{formError}</p>}
      </form>

      {state.phase === 'loading' && <p className="habits-loading">Chargement des habitudes…</p>}
      {state.phase === 'error' && <p className="habits-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {state.data.length === 0 && <p className="habits-empty">Aucune habitude pour l'instant.</p>}
          {state.data.length > 0 && <ul className="habits-list">{state.data.map(renderHabit)}</ul>}
        </>
      )}
    </div>
  )
}

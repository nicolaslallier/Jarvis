import { useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useTasks } from './useTasks'
import type { Task, TaskPriority, TaskStatus, TaskUpdateInput } from './useTasks'

const PRIORITY_LABELS: Record<TaskPriority, string> = {
  low: 'Basse',
  normal: 'Normale',
  high: 'Haute',
}

const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'À faire',
  doing: 'En cours',
  done: 'Terminée',
  cancelled: 'Annulée',
}

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function toDatetimeLocalValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function startOfDay(date: Date): Date {
  const d = new Date(date)
  d.setHours(0, 0, 0, 0)
  return d
}

function formatDueLabel(dueAt: string): { label: string; overdue: boolean } {
  const due = new Date(dueAt)
  const now = new Date()
  const diffDays = Math.round((startOfDay(due).getTime() - startOfDay(now).getTime()) / 86_400_000)
  const hasTime = due.getHours() !== 0 || due.getMinutes() !== 0
  const timeSuffix = hasTime ? ` à ${due.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}` : ''

  if (diffDays === 0) return { label: `Aujourd'hui${timeSuffix}`, overdue: due.getTime() < now.getTime() }
  if (diffDays === 1) return { label: `Demain${timeSuffix}`, overdue: false }
  if (diffDays < 0) return { label: `En retard de ${-diffDays} j`, overdue: true }
  if (diffDays <= 6) {
    return { label: due.toLocaleDateString('fr-FR', { weekday: 'long' }) + timeSuffix, overdue: false }
  }
  return {
    label: due.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' }) + timeSuffix,
    overdue: false,
  }
}

function isOpen(status: TaskStatus): boolean {
  return status === 'todo' || status === 'doing'
}

function defaultCreateForm() {
  return { title: '', description: '', dueAt: '', priority: 'normal' as TaskPriority, project: '', tags: '' }
}

type CreateForm = ReturnType<typeof defaultCreateForm>

function editFormFrom(task: Task) {
  return {
    title: task.title,
    description: task.description ?? '',
    dueAt: task.due_at ? toDatetimeLocalValue(new Date(task.due_at)) : '',
    status: task.status,
    priority: task.priority,
    project: task.project ?? '',
    tags: task.tags?.join(', ') ?? '',
  }
}

type EditForm = ReturnType<typeof editFormFrom>

function parseTags(value: string): string[] | null {
  const tags = value
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean)
  return tags.length > 0 ? tags : null
}

export default function TasksPage() {
  const { state, createTask, deleteTask, updateTask } = useTasks()
  const [form, setForm] = useState<CreateForm>(defaultCreateForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const formRef = useRef<HTMLFormElement>(null)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<EditForm | null>(null)

  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [pendingIds, setPendingIds] = useState<Set<number>>(new Set())
  const [showDone, setShowDone] = useState(false)

  const [search, setSearch] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [priorityFilter, setPriorityFilter] = useState<TaskPriority | ''>('')
  const [thisWeekOnly, setThisWeekOnly] = useState(false)

  const projects = useMemo(() => {
    if (state.phase !== 'ok') return []
    const set = new Set<string>()
    for (const t of state.data) if (t.project) set.add(t.project)
    return [...set].sort()
  }, [state])

  const filtered = useMemo(() => {
    if (state.phase !== 'ok') return []
    const q = search.trim().toLowerCase()
    const weekLimit = Date.now() + 7 * 86_400_000
    return state.data.filter((t) => {
      if (q && !t.title.toLowerCase().includes(q) && !(t.description ?? '').toLowerCase().includes(q)) {
        return false
      }
      if (projectFilter && t.project !== projectFilter) return false
      if (priorityFilter && t.priority !== priorityFilter) return false
      if (thisWeekOnly && (!t.due_at || new Date(t.due_at).getTime() > weekLimit)) return false
      return true
    })
  }, [state, search, projectFilter, priorityFilter, thisWeekOnly])

  const now = Date.now()
  const overdue = filtered.filter((t) => isOpen(t.status) && t.due_at && new Date(t.due_at).getTime() < now)
  const overdueIds = new Set(overdue.map((t) => t.id))
  const upcoming = filtered.filter((t) => isOpen(t.status) && !overdueIds.has(t.id))
  const finished = filtered.filter((t) => !isOpen(t.status))

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
    setCreating(true)
    try {
      await createTask({
        title: form.title,
        description: form.description.trim() || undefined,
        due_at: form.dueAt ? new Date(form.dueAt).toISOString() : undefined,
        priority: form.priority,
        project: form.project.trim() || undefined,
        tags: parseTags(form.tags) ?? undefined,
      })
      setForm(defaultCreateForm())
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function handleFormKeyDown(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      formRef.current?.requestSubmit()
    }
  }

  function toggleDone(task: Task) {
    runRowAction(task.id, () =>
      updateTask(task.id, { status: task.status === 'done' ? 'todo' : 'done' }),
    )
  }

  function startEdit(task: Task) {
    setEditingId(task.id)
    setEditForm(editFormFrom(task))
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm(null)
  }

  function handleSave(id: number) {
    if (!editForm) return
    const input: TaskUpdateInput = {
      title: editForm.title,
      description: editForm.description.trim() === '' ? null : editForm.description,
      due_at: editForm.dueAt === '' ? null : new Date(editForm.dueAt).toISOString(),
      status: editForm.status,
      priority: editForm.priority,
      project: editForm.project.trim() === '' ? null : editForm.project,
      tags: parseTags(editForm.tags),
    }
    runRowAction(id, async () => {
      await updateTask(id, input)
      setEditingId(null)
      setEditForm(null)
    })
  }

  function handleDelete(task: Task) {
    if (!confirm(`Supprimer la tâche « ${task.title} » ? Cette action est définitive.`)) return
    runRowAction(task.id, () => deleteTask(task.id))
  }

  function renderTask(task: Task) {
    const pending = pendingIds.has(task.id)
    const dueInfo = task.due_at ? formatDueLabel(task.due_at) : null

    if (editingId === task.id && editForm) {
      return (
        <li key={task.id} className="task-item">
          <div className="task-edit">
            <input
              type="text"
              value={editForm.title}
              onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
              required
              className="task-edit-title"
            />
            <textarea
              value={editForm.description}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
              placeholder="Description (optionnel)"
              className="task-edit-desc"
            />
            <div className="task-edit-row">
              <input
                type="datetime-local"
                value={editForm.dueAt}
                onChange={(e) => setEditForm({ ...editForm, dueAt: e.target.value })}
                className="task-edit-date"
              />
              <select
                value={editForm.status}
                onChange={(e) => setEditForm({ ...editForm, status: e.target.value as TaskStatus })}
              >
                {(Object.keys(STATUS_LABELS) as TaskStatus[]).map((s) => (
                  <option key={s} value={s}>
                    {STATUS_LABELS[s]}
                  </option>
                ))}
              </select>
              <select
                value={editForm.priority}
                onChange={(e) => setEditForm({ ...editForm, priority: e.target.value as TaskPriority })}
              >
                {(Object.keys(PRIORITY_LABELS) as TaskPriority[]).map((p) => (
                  <option key={p} value={p}>
                    {PRIORITY_LABELS[p]}
                  </option>
                ))}
              </select>
            </div>
            <div className="task-edit-row">
              <input
                type="text"
                placeholder="Projet (optionnel)"
                value={editForm.project}
                onChange={(e) => setEditForm({ ...editForm, project: e.target.value })}
              />
              <input
                type="text"
                placeholder="Étiquettes séparées par des virgules"
                value={editForm.tags}
                onChange={(e) => setEditForm({ ...editForm, tags: e.target.value })}
              />
            </div>
            <div className="task-edit-actions">
              <button type="button" onClick={() => handleSave(task.id)} disabled={pending}>
                {pending ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" onClick={cancelEdit} disabled={pending}>
                Annuler
              </button>
            </div>
            {rowErrors[task.id] && <p className="tasks-row-error">{rowErrors[task.id]}</p>}
          </div>
        </li>
      )
    }

    return (
      <li key={task.id} className={`task-item priority-${task.priority} ${!isOpen(task.status) ? 'task-item-done' : ''}`}>
        <div className="task-item-main">
          <label className="task-checkbox">
            <input
              type="checkbox"
              checked={task.status === 'done'}
              disabled={pending}
              onChange={() => toggleDone(task)}
            />
            <strong>{task.title}</strong>
          </label>
          {dueInfo && (
            <span className={`task-due-date ${dueInfo.overdue ? 'task-due-overdue' : ''}`}>{dueInfo.label}</span>
          )}
        </div>
        <div className="task-item-meta">
          {task.status !== 'todo' && task.status !== 'done' && (
            <span className="task-badge task-status-badge">{STATUS_LABELS[task.status]}</span>
          )}
          {task.priority !== 'normal' && (
            <span className={`task-badge task-priority-badge priority-${task.priority}`}>
              {PRIORITY_LABELS[task.priority]}
            </span>
          )}
          {task.project && <span className="task-badge task-project-badge">{task.project}</span>}
          {task.tags?.map((tag) => (
            <span key={tag} className="task-badge task-tag-badge">
              #{tag}
            </span>
          ))}
        </div>
        {task.description && <p className="task-description">{task.description}</p>}
        <div className="task-item-actions">
          <button type="button" onClick={() => startEdit(task)} className="task-edit-btn" disabled={pending}>
            Modifier
          </button>
          <button type="button" onClick={() => handleDelete(task)} className="task-delete" disabled={pending}>
            {pending ? '…' : 'Supprimer'}
          </button>
        </div>
        {rowErrors[task.id] && <p className="tasks-row-error">{rowErrors[task.id]}</p>}
      </li>
    )
  }

  return (
    <div className="tasks">
      <h1>Tâches</h1>

      <form className="tasks-form" ref={formRef} onSubmit={handleSubmit} onKeyDown={handleFormKeyDown}>
        <input
          type="text"
          placeholder="Titre"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          required
        />
        <textarea
          placeholder="Description (optionnel)"
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
        />
        <div className="task-edit-row">
          <input
            type="datetime-local"
            value={form.dueAt}
            onChange={(e) => setForm({ ...form, dueAt: e.target.value })}
          />
          <select
            value={form.priority}
            onChange={(e) => setForm({ ...form, priority: e.target.value as TaskPriority })}
          >
            {(Object.keys(PRIORITY_LABELS) as TaskPriority[]).map((p) => (
              <option key={p} value={p}>
                {PRIORITY_LABELS[p]}
              </option>
            ))}
          </select>
        </div>
        <div className="task-edit-row">
          <input
            type="text"
            placeholder="Projet (optionnel)"
            value={form.project}
            onChange={(e) => setForm({ ...form, project: e.target.value })}
          />
          <input
            type="text"
            placeholder="Étiquettes séparées par des virgules"
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
          />
        </div>
        <button type="submit" disabled={creating}>
          {creating ? 'Ajout…' : 'Ajouter (Ctrl+Entrée)'}
        </button>
        {formError && <p className="tasks-form-error">{formError}</p>}
      </form>

      <div className="tasks-filters">
        <input
          type="text"
          placeholder="Rechercher…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
          <option value="">Tous les projets</option>
          {projects.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <select
          value={priorityFilter}
          onChange={(e) => setPriorityFilter(e.target.value as TaskPriority | '')}
        >
          <option value="">Toutes les priorités</option>
          {(Object.keys(PRIORITY_LABELS) as TaskPriority[]).map((p) => (
            <option key={p} value={p}>
              {PRIORITY_LABELS[p]}
            </option>
          ))}
        </select>
        <label className="tasks-filter-checkbox">
          <input
            type="checkbox"
            checked={thisWeekOnly}
            onChange={(e) => setThisWeekOnly(e.target.checked)}
          />
          Cette semaine
        </label>
      </div>

      {state.phase === 'loading' && <p className="tasks-loading">Chargement des tâches…</p>}
      {state.phase === 'error' && <p className="tasks-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {filtered.length === 0 && <p className="tasks-empty">Aucune tâche.</p>}

          {overdue.length > 0 && (
            <section className="tasks-section">
              <h2 className="tasks-section-title tasks-section-overdue">En retard ({overdue.length})</h2>
              <ul className="tasks-list">{overdue.map(renderTask)}</ul>
            </section>
          )}

          {upcoming.length > 0 && (
            <section className="tasks-section">
              <h2 className="tasks-section-title">À faire ({upcoming.length})</h2>
              <ul className="tasks-list">{upcoming.map(renderTask)}</ul>
            </section>
          )}

          {finished.length > 0 && (
            <section className="tasks-section">
              <button type="button" className="tasks-section-toggle" onClick={() => setShowDone((v) => !v)}>
                {showDone ? '▾' : '▸'} Terminé ({finished.length})
              </button>
              {showDone && <ul className="tasks-list">{finished.map(renderTask)}</ul>}
            </section>
          )}
        </>
      )}
    </div>
  )
}

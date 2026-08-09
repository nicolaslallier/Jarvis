import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTasks } from './useTasks'

export default function TasksPage() {
  const { state, createTask, completeTask, deleteTask, updateTask } = useTasks()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  // Inline editing state
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editDueDate, setEditDueDate] = useState('')

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await createTask({
        title,
        description: description || undefined,
        due_date: dueDate || undefined,
      })
      setTitle('')
      setDescription('')
      setDueDate('')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleComplete(id: number) {
    try {
      await completeTask(id)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  function startEdit(task: { id: number; title: string; description: string | null; due_date: string | null }) {
    setEditingId(task.id)
    setEditTitle(task.title)
    setEditDescription(task.description ?? '')
    setEditDueDate(task.due_date ?? '')
  }

  async function handleSave(id: number) {
    setFormError(null)
    try {
      await updateTask(id, {
        title: editTitle,
        description: editDescription || undefined,
        due_date: editDueDate || undefined,
      })
      setEditingId(null)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  function cancelEdit() {
    setEditingId(null)
  }

  return (
    <div className="tasks">
      <h1>Tasks</h1>

      <form className="tasks-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <textarea
          placeholder="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <input
          type="date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
        />
        <button type="submit">Add task</button>
        {formError && <p className="tasks-form-error">{formError}</p>}
      </form>

      {state.phase === 'loading' && <p className="tasks-loading">Loading tasks…</p>}
      {state.phase === 'error' && <p className="tasks-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <ul className="tasks-list">
          {state.data.length === 0 && <li className="tasks-empty">No tasks yet.</li>}
          {state.data.map((task) => (
            <li key={task.id} className={`task-item ${task.done ? 'task-item-done' : ''}`}>
              {editingId === task.id ? (
                <div className="task-edit">
                  <input
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    required
                    className="task-edit-title"
                  />
                  <textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    className="task-edit-desc"
                  />
                  <input
                    type="date"
                    value={editDueDate}
                    onChange={(e) => setEditDueDate(e.target.value)}
                    className="task-edit-date"
                  />
                  <div className="task-edit-actions">
                    <button type="button" onClick={() => handleSave(task.id)}>Save</button>
                    <button type="button" onClick={cancelEdit}>Cancel</button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="task-item-main">
                    <strong>{task.title}</strong>
                    {task.due_date && <span className="task-due-date">Due {task.due_date}</span>}
                  </div>
                  {task.description && <p className="task-description">{task.description}</p>}
                  {!task.done && (
                    <button type="button" onClick={() => handleComplete(task.id)}>
                      Mark done
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => startEdit(task)}
                    className="task-edit-btn"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteTask(task.id)}
                    className="task-delete"
                  >
                    Delete
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

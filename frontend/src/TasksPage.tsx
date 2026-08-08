import { useState } from 'react'
import type { FormEvent } from 'react'
import { useTasks } from './useTasks'

export default function TasksPage() {
  const { state, createTask, completeTask } = useTasks()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

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
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

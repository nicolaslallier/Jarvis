import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMeetingSummaries } from './useMeetingSummaries'
import type { MeetingSummary, MeetingSummaryUpdateInput } from './useMeetingSummaries'
import { useCalendar } from './useCalendar'

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function toDatetimeLocalValue(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatMeetingDate(value: string): string {
  return new Date(value).toLocaleString('fr-FR', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function truncate(text: string, length: number): string {
  return text.length <= length ? text : text.slice(0, length).trimEnd() + '…'
}

function defaultForm() {
  return { title: '', meetingDate: '', participants: '', content: '', appointmentId: '' }
}

type FormState = ReturnType<typeof defaultForm>

function editFormFrom(summary: MeetingSummary): FormState {
  return {
    title: summary.title,
    meetingDate: toDatetimeLocalValue(new Date(summary.meeting_date)),
    participants: summary.participants ?? '',
    content: summary.content,
    appointmentId: summary.appointment_id ? String(summary.appointment_id) : '',
  }
}

export default function MeetingSummariesPage() {
  const { state, createMeetingSummary, updateMeetingSummary, deleteMeetingSummary } = useMeetingSummaries()
  const { state: appointmentsState } = useCalendar()
  const appointments = appointmentsState.phase === 'ok' ? appointmentsState.data : []

  const [form, setForm] = useState<FormState>(defaultForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState<FormState | null>(null)

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

    if (!form.meetingDate) {
      setFormError('La date de la réunion est requise.')
      return
    }

    setCreating(true)
    try {
      await createMeetingSummary({
        title: form.title,
        meeting_date: new Date(form.meetingDate).toISOString(),
        content: form.content,
        participants: form.participants.trim() || undefined,
        appointment_id: form.appointmentId ? Number(form.appointmentId) : undefined,
      })
      setForm(defaultForm())
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function startEdit(summary: MeetingSummary) {
    setEditingId(summary.id)
    setEditForm(editFormFrom(summary))
  }

  function cancelEdit() {
    setEditingId(null)
    setEditForm(null)
  }

  function handleSave(id: number) {
    if (!editForm) return
    const input: MeetingSummaryUpdateInput = {
      title: editForm.title,
      meeting_date: new Date(editForm.meetingDate).toISOString(),
      content: editForm.content,
      participants: editForm.participants.trim() || null,
      appointment_id: editForm.appointmentId ? Number(editForm.appointmentId) : null,
    }
    runRowAction(id, async () => {
      await updateMeetingSummary(id, input)
      setEditingId(null)
      setEditForm(null)
    })
  }

  function handleDelete(summary: MeetingSummary) {
    if (!confirm(`Supprimer le résumé « ${summary.title} » ? Cette action est définitive.`)) return
    runRowAction(summary.id, () => deleteMeetingSummary(summary.id))
  }

  function renderSummary(summary: MeetingSummary) {
    const pending = pendingIds.has(summary.id)

    if (editingId === summary.id && editForm) {
      return (
        <li key={summary.id} className="task-item">
          <div className="task-edit">
            <input
              type="text"
              value={editForm.title}
              onChange={(e) => setEditForm({ ...editForm, title: e.target.value })}
              required
              className="task-edit-title"
            />
            <div className="task-edit-row">
              <input
                type="datetime-local"
                value={editForm.meetingDate}
                onChange={(e) => setEditForm({ ...editForm, meetingDate: e.target.value })}
                required
              />
              <input
                type="text"
                placeholder="Participants (optionnel)"
                value={editForm.participants}
                onChange={(e) => setEditForm({ ...editForm, participants: e.target.value })}
              />
            </div>
            <select
              value={editForm.appointmentId}
              onChange={(e) => setEditForm({ ...editForm, appointmentId: e.target.value })}
            >
              <option value="">— Aucun rendez-vous lié —</option>
              {appointments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            </select>
            <textarea
              value={editForm.content}
              onChange={(e) => setEditForm({ ...editForm, content: e.target.value })}
              placeholder="Contenu du résumé"
              className="task-edit-desc"
              required
            />
            <div className="task-edit-actions">
              <button type="button" onClick={() => handleSave(summary.id)} disabled={pending}>
                {pending ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" onClick={cancelEdit} disabled={pending}>
                Annuler
              </button>
            </div>
            {rowErrors[summary.id] && <p className="tasks-row-error">{rowErrors[summary.id]}</p>}
          </div>
        </li>
      )
    }

    const linkedAppointment = appointments.find((a) => a.id === summary.appointment_id)

    return (
      <li key={summary.id} className="task-item">
        <div className="task-item-main">
          <strong>{summary.title}</strong>
          <span className="task-due-date">{formatMeetingDate(summary.meeting_date)}</span>
        </div>
        <div className="task-item-meta">
          {summary.participants && (
            <span className="task-badge task-project-badge">{summary.participants}</span>
          )}
          {linkedAppointment && (
            <span className="task-badge task-status-badge">Lié : {linkedAppointment.title}</span>
          )}
        </div>
        <p className="task-description">{truncate(summary.content, 240)}</p>
        <div className="task-item-actions">
          <button type="button" onClick={() => startEdit(summary)} className="task-edit-btn" disabled={pending}>
            Modifier
          </button>
          <button type="button" onClick={() => handleDelete(summary)} className="task-delete" disabled={pending}>
            {pending ? '…' : 'Supprimer'}
          </button>
        </div>
        {rowErrors[summary.id] && <p className="tasks-row-error">{rowErrors[summary.id]}</p>}
      </li>
    )
  }

  return (
    <div className="tasks">
      <h1>Résumés de réunion</h1>

      <form className="tasks-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Titre"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          required
        />
        <div className="task-edit-row">
          <input
            type="datetime-local"
            value={form.meetingDate}
            onChange={(e) => setForm({ ...form, meetingDate: e.target.value })}
            required
          />
          <input
            type="text"
            placeholder="Participants (optionnel)"
            value={form.participants}
            onChange={(e) => setForm({ ...form, participants: e.target.value })}
          />
        </div>
        <select
          value={form.appointmentId}
          onChange={(e) => setForm({ ...form, appointmentId: e.target.value })}
        >
          <option value="">— Aucun rendez-vous lié —</option>
          {appointments.map((a) => (
            <option key={a.id} value={a.id}>
              {a.title}
            </option>
          ))}
        </select>
        <textarea
          placeholder="Contenu du résumé"
          value={form.content}
          onChange={(e) => setForm({ ...form, content: e.target.value })}
          required
        />
        <button type="submit" disabled={creating}>
          {creating ? 'Ajout…' : 'Ajouter'}
        </button>
        {formError && <p className="tasks-form-error">{formError}</p>}
      </form>

      {state.phase === 'loading' && <p className="tasks-loading">Chargement des résumés…</p>}
      {state.phase === 'error' && <p className="tasks-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {state.data.length === 0 && <p className="tasks-empty">Aucun résumé de réunion.</p>}
          <ul className="tasks-list">{state.data.map(renderSummary)}</ul>
        </>
      )}
    </div>
  )
}

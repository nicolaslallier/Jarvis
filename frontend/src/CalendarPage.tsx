import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { useCalendar } from './useCalendar'
import type { Appointment } from './useCalendar'

const WEEKDAY_LABELS = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam']

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function dateKey(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function toDatetimeLocalValue(date: Date): string {
  return `${dateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function buildMonthGrid(monthStart: Date): Date[] {
  const gridStart = new Date(monthStart)
  gridStart.setDate(gridStart.getDate() - gridStart.getDay())
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(gridStart)
    d.setDate(gridStart.getDate() + i)
    return d
  })
}

function defaultFormState(day: Date) {
  const start = new Date(day)
  start.setHours(9, 0, 0, 0)
  const end = new Date(day)
  end.setHours(10, 0, 0, 0)
  return {
    title: '',
    startTime: toDatetimeLocalValue(start),
    endTime: toDatetimeLocalValue(end),
    location: '',
    description: '',
    allDay: false,
  }
}

type FormState = ReturnType<typeof defaultFormState>

export default function CalendarPage() {
  const { state, createAppointment, updateAppointment, deleteAppointment } = useCalendar()
  const today = useMemo(() => new Date(), [])
  const [monthStart, setMonthStart] = useState(() => new Date(today.getFullYear(), today.getMonth(), 1))
  const [selectedDate, setSelectedDate] = useState(() => new Date(today))
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form, setForm] = useState<FormState>(() => defaultFormState(today))
  const [formError, setFormError] = useState<string | null>(null)

  const appointmentsByDay = useMemo(() => {
    const map = new Map<string, Appointment[]>()
    if (state.phase !== 'ok') return map
    for (const appointment of state.data) {
      const key = dateKey(new Date(appointment.start_time))
      const existing = map.get(key)
      if (existing) existing.push(appointment)
      else map.set(key, [appointment])
    }
    return map
  }, [state])

  const grid = useMemo(() => buildMonthGrid(monthStart), [monthStart])
  const selectedKey = dateKey(selectedDate)
  const selectedAppointments = appointmentsByDay.get(selectedKey) ?? []

  function goToMonth(offset: number) {
    setMonthStart((prev) => new Date(prev.getFullYear(), prev.getMonth() + offset, 1))
  }

  function selectDay(day: Date) {
    setSelectedDate(day)
    setEditingId(null)
    setFormError(null)
    setForm(defaultFormState(day))
  }

  function startEdit(appointment: Appointment) {
    setSelectedDate(new Date(appointment.start_time))
    setEditingId(appointment.id)
    setFormError(null)
    setForm({
      title: appointment.title,
      startTime: toDatetimeLocalValue(new Date(appointment.start_time)),
      endTime: toDatetimeLocalValue(new Date(appointment.end_time)),
      location: appointment.location ?? '',
      description: appointment.description ?? '',
      allDay: appointment.all_day,
    })
  }

  function cancelEdit() {
    setEditingId(null)
    setFormError(null)
    setForm(defaultFormState(selectedDate))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)

    const startTime = new Date(form.startTime)
    const endTime = new Date(form.endTime)
    if (endTime < startTime) {
      setFormError("L'heure de fin doit être après l'heure de début.")
      return
    }

    const input = {
      title: form.title,
      start_time: startTime.toISOString(),
      end_time: endTime.toISOString(),
      location: form.location || undefined,
      description: form.description || undefined,
      all_day: form.allDay,
    }

    try {
      if (editingId !== null) {
        await updateAppointment(editingId, input)
        setEditingId(null)
      } else {
        await createAppointment(input)
      }
      setForm(defaultFormState(selectedDate))
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  async function handleDelete(id: number) {
    setFormError(null)
    try {
      await deleteAppointment(id)
      if (editingId === id) cancelEdit()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="calendar">
      <h1>Calendrier</h1>

      {state.phase === 'loading' && <p className="calendar-loading">Chargement des rendez-vous…</p>}
      {state.phase === 'error' && <p className="calendar-form-error">{state.message}</p>}

      {state.phase !== 'loading' && (
        <>
          <div className="calendar-month-nav">
            <button type="button" onClick={() => goToMonth(-1)}>
              ← Préc.
            </button>
            <strong className="calendar-month-label">
              {monthStart.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })}
            </strong>
            <button type="button" onClick={() => goToMonth(1)}>
              Suiv. →
            </button>
            <button type="button" onClick={() => setMonthStart(new Date(today.getFullYear(), today.getMonth(), 1))}>
              Aujourd'hui
            </button>
          </div>

          <div className="calendar-grid">
            {WEEKDAY_LABELS.map((label) => (
              <div key={label} className="calendar-weekday">
                {label}
              </div>
            ))}
            {grid.map((day) => {
              const key = dateKey(day)
              const dayAppointments = appointmentsByDay.get(key) ?? []
              const classes = [
                'calendar-day',
                day.getMonth() !== monthStart.getMonth() ? 'calendar-day-outside' : '',
                key === dateKey(today) ? 'calendar-day-today' : '',
                key === selectedKey ? 'calendar-day-selected' : '',
              ]
                .filter(Boolean)
                .join(' ')

              return (
                <button
                  type="button"
                  key={key}
                  className={classes}
                  onClick={() => selectDay(day)}
                >
                  <span className="calendar-day-number">{day.getDate()}</span>
                  <span className="calendar-day-chips">
                    {dayAppointments.slice(0, 3).map((a) => (
                      <span
                        key={a.id}
                        className="calendar-chip"
                        onClick={(e) => {
                          e.stopPropagation()
                          startEdit(a)
                        }}
                      >
                        {a.title}
                      </span>
                    ))}
                    {dayAppointments.length > 3 && (
                      <span className="calendar-chip-more">+{dayAppointments.length - 3} autres</span>
                    )}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="calendar-day-detail">
            <h2>
              {selectedDate.toLocaleDateString(undefined, {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
              })}
            </h2>

            {selectedAppointments.length === 0 && (
              <p className="calendar-empty">Aucun rendez-vous ce jour-là.</p>
            )}
            <ul className="calendar-appointment-list">
              {selectedAppointments.map((a) => (
                <li key={a.id} className="calendar-appointment-item">
                  <div className="calendar-appointment-main">
                    <strong>{a.title}</strong>
                    <span className="calendar-appointment-time">
                      {a.all_day
                        ? 'Toute la journée'
                        : `${new Date(a.start_time).toLocaleTimeString(undefined, {
                            hour: 'numeric',
                            minute: '2-digit',
                          })} – ${new Date(a.end_time).toLocaleTimeString(undefined, {
                            hour: 'numeric',
                            minute: '2-digit',
                          })}`}
                    </span>
                  </div>
                  {a.location && <p className="calendar-appointment-location">{a.location}</p>}
                  {a.description && <p className="calendar-appointment-description">{a.description}</p>}
                  <div className="calendar-appointment-actions">
                    <button type="button" onClick={() => startEdit(a)}>
                      Modifier
                    </button>
                    <button type="button" className="calendar-delete" onClick={() => handleDelete(a.id)}>
                      Supprimer
                    </button>
                  </div>
                </li>
              ))}
            </ul>

            <form className="calendar-form" onSubmit={handleSubmit}>
              <h3>{editingId !== null ? 'Modifier le rendez-vous' : 'Nouveau rendez-vous'}</h3>
              <input
                type="text"
                placeholder="Titre"
                value={form.title}
                onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
                required
              />
              <label className="calendar-form-checkbox">
                <input
                  type="checkbox"
                  checked={form.allDay}
                  onChange={(e) => setForm((f) => ({ ...f, allDay: e.target.checked }))}
                />
                Toute la journée
              </label>
              <div className="calendar-form-times">
                <label>
                  Start
                  <input
                    type={form.allDay ? 'date' : 'datetime-local'}
                    value={form.allDay ? form.startTime.slice(0, 10) : form.startTime}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        startTime: form.allDay ? `${e.target.value}T00:00` : e.target.value,
                      }))
                    }
                    required
                  />
                </label>
                <label>
                  End
                  <input
                    type={form.allDay ? 'date' : 'datetime-local'}
                    value={form.allDay ? form.endTime.slice(0, 10) : form.endTime}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        endTime: form.allDay ? `${e.target.value}T00:00` : e.target.value,
                      }))
                    }
                    required
                  />
                </label>
              </div>
              <input
                type="text"
                placeholder="Lieu (optionnel)"
                value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))}
              />
              <textarea
                placeholder="Description (optionnel)"
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
              <div className="calendar-form-actions">
                <button type="submit">{editingId !== null ? 'Enregistrer' : 'Ajouter le rendez-vous'}</button>
                {editingId !== null && (
                  <button type="button" onClick={cancelEdit}>
                    Annuler
                  </button>
                )}
              </div>
              {formError && <p className="calendar-form-error">{formError}</p>}
            </form>
          </div>
        </>
      )}
    </div>
  )
}

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import DailyBriefing from './DailyBriefing'
import JournalNote from './JournalNote'
import SessionTimer from './SessionTimer'
import { useBriefing } from './useBriefing'
import type { Task } from './useTasks'
import type { Appointment } from './useCalendar'
import { useHabits } from './useHabits'
import type { Habit } from './useHabits'

// Self-contained page: styling lives in this file (not App.css), same
// convention as HabitsPage.tsx/ContactsPage.tsx, since this page composes
// several already-styled widgets plus a few new bits of its own.
const STYLES = `
.today-page { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: 2rem; }
.today-header { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 0.75rem; }
.today-section-title { margin: 0 0 0.5rem 0; }
.today-capture-form { display: flex; gap: 0.5rem; }
.today-capture-form input[type="text"] {
  flex: 1;
  padding: 0.6rem 0.9rem;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-h);
}
.today-capture-form button {
  padding: 0.6rem 1.1rem;
  border-radius: 6px;
  border: none;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
.today-capture-form button:disabled { opacity: 0.6; cursor: default; }
.today-capture-status { margin: 0.4rem 0 0 0; font-size: 0.9rem; }
.today-capture-status-sent { color: #2ecc71; }
.today-capture-status-error { color: #e74c3c; }
.today-habits-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.today-habit-item {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.today-empty { opacity: 0.7; font-size: 0.9rem; }
.today-habit-name { flex: 1; }
.today-review-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}
.today-review-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.6rem;
  padding: 0.5rem 0.75rem;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.today-review-kind {
  font-size: 0.75rem;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  background: var(--border);
  color: var(--accent);
  white-space: nowrap;
}
.today-review-title { flex: 1; min-width: 8rem; }
.today-review-when { font-size: 0.85rem; opacity: 0.75; }
.today-review-actions { display: flex; gap: 0.4rem; }
.today-review-confirm {
  padding: 0.3rem 0.7rem;
  border-radius: 6px;
  border: none;
  background: var(--accent);
  color: #fff;
  cursor: pointer;
}
.today-review-reject {
  padding: 0.3rem 0.7rem;
  border-radius: 6px;
  border: 1px solid #e74c3c;
  background: none;
  color: #e74c3c;
  cursor: pointer;
}
.today-review-confirm:disabled, .today-review-reject:disabled { opacity: 0.6; cursor: default; }
.today-review-error { flex-basis: 100%; margin: 0; font-size: 0.85rem; color: #e74c3c; }
`

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// How long the "Envoyé" confirmation stays visible after a successful
// quick-capture send, in milliseconds.
const CAPTURE_FEEDBACK_MS = 2000

type CaptureStatus =
  | { phase: 'idle' }
  | { phase: 'sending' }
  | { phase: 'sent' }
  | { phase: 'error'; message: string }

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Le serveur a répondu ${res.status}`
}

function isHabitDoneForWindow(habit: Habit): boolean {
  if (!habit.last_completed_at) return false
  const gapMs = Date.now() - new Date(habit.last_completed_at).getTime()
  // Mirrors HabitsPage.tsx's own approximation of the backend's streak
  // grace windows — good enough for "already done today/this week?".
  const windowMs = habit.frequency === 'weekly' ? 9 * 86_400_000 : 2 * 86_400_000
  return gapMs <= windowMs
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('fr-CA', {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatTodayLabel(): string {
  return new Date().toLocaleDateString('fr-CA', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

// The "À vérifier" section below fetches these two filtered endpoints
// directly (not via useTasks/useCalendar, which always load the full,
// unfiltered list) so email_ingest's draft rows — Task status='pending_review'
// or Appointment pending_review=true, both source='email_import' — never mix
// into any other list on this page.
type ReviewState<T> =
  | { phase: 'loading' }
  | { phase: 'ok'; data: T[] }
  | { phase: 'error'; message: string }

type ReviewItem =
  | { kind: 'task'; id: number; task: Task }
  | { kind: 'appointment'; id: number; appointment: Appointment }

export default function TodayPage() {
  const { state: briefingState, reload: reloadBriefing } = useBriefing()
  const { state: habitsState, completeHabit } = useHabits()

  const [captureText, setCaptureText] = useState('')
  const [captureStatus, setCaptureStatus] = useState<CaptureStatus>({ phase: 'idle' })
  const [pendingHabitIds, setPendingHabitIds] = useState<Set<number>>(new Set())

  const [reviewTasks, setReviewTasks] = useState<ReviewState<Task>>({ phase: 'loading' })
  const [reviewAppointments, setReviewAppointments] = useState<ReviewState<Appointment>>({
    phase: 'loading',
  })
  // Keyed "task-<id>"/"appointment-<id>" rather than a bare number, since
  // task and appointment ids are independent sequences and could collide.
  const [reviewPendingKeys, setReviewPendingKeys] = useState<Set<string>>(new Set())
  const [reviewRowErrors, setReviewRowErrors] = useState<Record<string, string>>({})

  const loadReviews = useCallback(() => {
    setReviewTasks({ phase: 'loading' })
    setReviewAppointments({ phase: 'loading' })

    fetch(`${API_URL}/tasks?status=pending_review`)
      .then(async (res) => {
        if (res.ok) {
          setReviewTasks({ phase: 'ok', data: await res.json() })
        } else {
          setReviewTasks({ phase: 'error', message: await errorMessage(res) })
        }
      })
      .catch((err) => {
        setReviewTasks({
          phase: 'error',
          message: `Erreur réseau : ${err instanceof Error ? err.message : String(err)}`,
        })
      })

    fetch(`${API_URL}/calendar/appointments?pending_review=true`)
      .then(async (res) => {
        if (res.ok) {
          setReviewAppointments({ phase: 'ok', data: await res.json() })
        } else {
          setReviewAppointments({ phase: 'error', message: await errorMessage(res) })
        }
      })
      .catch((err) => {
        setReviewAppointments({
          phase: 'error',
          message: `Erreur réseau : ${err instanceof Error ? err.message : String(err)}`,
        })
      })
  }, [])

  useEffect(() => {
    loadReviews()
  }, [loadReviews])

  const reviewItems: ReviewItem[] = useMemo(() => {
    const items: ReviewItem[] = []
    if (reviewTasks.phase === 'ok') {
      items.push(...reviewTasks.data.map((task) => ({ kind: 'task' as const, id: task.id, task })))
    }
    if (reviewAppointments.phase === 'ok') {
      items.push(
        ...reviewAppointments.data.map((appointment) => ({
          kind: 'appointment' as const,
          id: appointment.id,
          appointment,
        })),
      )
    }
    return items
  }, [reviewTasks, reviewAppointments])

  function runReviewAction(key: string, action: () => Promise<void>) {
    setReviewRowErrors((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    setReviewPendingKeys((prev) => new Set(prev).add(key))
    action()
      .catch((err) => {
        setReviewRowErrors((prev) => ({ ...prev, [key]: err instanceof Error ? err.message : String(err) }))
      })
      .finally(() => {
        setReviewPendingKeys((prev) => {
          const next = new Set(prev)
          next.delete(key)
          return next
        })
      })
  }

  function confirmReviewTask(id: number) {
    runReviewAction(`task-${id}`, async () => {
      const res = await fetch(`${API_URL}/tasks/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'todo' }),
      })
      if (!res.ok) throw new Error(await errorMessage(res))
      setReviewTasks((prev) =>
        prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((t) => t.id !== id) } : prev,
      )
    })
  }

  function rejectReviewTask(id: number) {
    runReviewAction(`task-${id}`, async () => {
      const res = await fetch(`${API_URL}/tasks/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await errorMessage(res))
      setReviewTasks((prev) =>
        prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((t) => t.id !== id) } : prev,
      )
    })
  }

  function confirmReviewAppointment(id: number) {
    runReviewAction(`appointment-${id}`, async () => {
      const res = await fetch(`${API_URL}/calendar/appointments/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pending_review: false }),
      })
      if (!res.ok) throw new Error(await errorMessage(res))
      setReviewAppointments((prev) =>
        prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((a) => a.id !== id) } : prev,
      )
    })
  }

  function rejectReviewAppointment(id: number) {
    runReviewAction(`appointment-${id}`, async () => {
      const res = await fetch(`${API_URL}/calendar/appointments/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await errorMessage(res))
      setReviewAppointments((prev) =>
        prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((a) => a.id !== id) } : prev,
      )
    })
  }

  async function handleCaptureSubmit(e: FormEvent) {
    e.preventDefault()
    const content = captureText.trim()
    if (!content) return

    setCaptureStatus({ phase: 'sending' })
    try {
      // Quick capture always starts a fresh, lightweight chat session for
      // the note — simplest option given useChat's session-management
      // hook isn't reused here (this is a fire-and-forget capture box, not
      // a chat window), and it keeps each capture traceable in Chat's
      // session list rather than accumulating into one giant thread.
      const sessionRes = await fetch(`${API_URL}/chat/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!sessionRes.ok) {
        setCaptureStatus({ phase: 'error', message: await errorMessage(sessionRes) })
        return
      }
      const session: { id: number } = await sessionRes.json()

      const messageRes = await fetch(`${API_URL}/chat/sessions/${session.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (!messageRes.ok || !messageRes.body) {
        setCaptureStatus({
          phase: 'error',
          message: messageRes.ok ? 'Réponse vide du serveur' : await errorMessage(messageRes),
        })
        return
      }
      const body = messageRes.body

      // The user gets their confirmation the instant the send is accepted —
      // waiting on the full LLM generation here is what made capture feel
      // broken (see docs/plan-refonte-accueil.md, point 6).
      setCaptureText('')
      setCaptureStatus({ phase: 'sent' })
      setTimeout(() => {
        setCaptureStatus((current) => (current.phase === 'sent' ? { phase: 'idle' } : current))
      }, CAPTURE_FEEDBACK_MS)

      // Still drain the stream in the background — the secretary's tool
      // calls (creating a task/appointment, etc.) only run as it's
      // consumed — then refresh whatever it may have created.
      ;(async () => {
        try {
          const reader = body.getReader()
          while (true) {
            const { done } = await reader.read()
            if (done) break
          }
        } catch {
          // best-effort drain — a network hiccup here shouldn't surface an error
        } finally {
          reloadBriefing()
          loadReviews()
        }
      })()
    } catch (err) {
      setCaptureStatus({
        phase: 'error',
        message: `Erreur réseau : ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  function handleHabitCheck(habit: Habit) {
    if (pendingHabitIds.has(habit.id) || isHabitDoneForWindow(habit)) return
    setPendingHabitIds((prev) => new Set(prev).add(habit.id))
    completeHabit(habit.id).finally(() => {
      setPendingHabitIds((prev) => {
        const next = new Set(prev)
        next.delete(habit.id)
        return next
      })
    })
  }

  const capturing = captureStatus.phase === 'sending'

  return (
    <div className="today-page">
      <style>{STYLES}</style>

      <div className="today-header">
        <h1>Aujourd'hui — {formatTodayLabel()}</h1>
        <SessionTimer />
      </div>

      <section>
        <h2 className="today-section-title">Capture rapide</h2>
        <form className="today-capture-form" onSubmit={handleCaptureSubmit}>
          <input
            type="text"
            value={captureText}
            onChange={(e) => setCaptureText(e.target.value)}
            placeholder="Notez une tâche, un rendez-vous, une pensée…"
            disabled={capturing}
          />
          <button type="submit" disabled={capturing || !captureText.trim()}>
            {capturing ? 'Envoi…' : 'Envoyer'}
          </button>
        </form>
        {captureStatus.phase === 'sent' && (
          <p className="today-capture-status today-capture-status-sent">Envoyé ✓</p>
        )}
        {captureStatus.phase === 'error' && (
          <p className="today-capture-status today-capture-status-error">{captureStatus.message}</p>
        )}
      </section>

      <DailyBriefing state={briefingState} />

      {(reviewItems.length > 0 || reviewTasks.phase === 'loading' || reviewAppointments.phase === 'loading') && (
        <section>
          <h2 className="today-section-title">À vérifier</h2>
          {reviewTasks.phase === 'error' && <p className="today-empty">{reviewTasks.message}</p>}
          {reviewAppointments.phase === 'error' && (
            <p className="today-empty">{reviewAppointments.message}</p>
          )}
          {(reviewTasks.phase === 'loading' || reviewAppointments.phase === 'loading') && (
            <p className="today-empty">Chargement…</p>
          )}
          {reviewItems.length === 0 &&
            reviewTasks.phase !== 'loading' &&
            reviewAppointments.phase !== 'loading' && (
              <p className="today-empty">Rien à vérifier.</p>
            )}
          {reviewItems.length > 0 && (
            <ul className="today-review-list">
              {reviewItems.map((item) => {
                const key = `${item.kind}-${item.id}`
                const pending = reviewPendingKeys.has(key)
                const title = item.kind === 'task' ? item.task.title : item.appointment.title
                const when =
                  item.kind === 'task'
                    ? item.task.due_at
                      ? formatDateTime(item.task.due_at)
                      : ''
                    : formatDateTime(item.appointment.start_time)
                return (
                  <li key={key} className="today-review-item">
                    <span className="today-review-kind">{item.kind === 'task' ? 'Tâche' : 'RDV'}</span>
                    <span className="today-review-title">{title}</span>
                    {when && <span className="today-review-when">{when}</span>}
                    <span className="today-review-actions">
                      <button
                        type="button"
                        className="today-review-confirm"
                        disabled={pending}
                        onClick={() =>
                          item.kind === 'task'
                            ? confirmReviewTask(item.id)
                            : confirmReviewAppointment(item.id)
                        }
                      >
                        Confirmer
                      </button>
                      <button
                        type="button"
                        className="today-review-reject"
                        disabled={pending}
                        onClick={() =>
                          item.kind === 'task'
                            ? rejectReviewTask(item.id)
                            : rejectReviewAppointment(item.id)
                        }
                      >
                        Rejeter
                      </button>
                    </span>
                    {reviewRowErrors[key] && <p className="today-review-error">{reviewRowErrors[key]}</p>}
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      )}

      {habitsState.phase === 'error' && (
        <section>
          <h2 className="today-section-title">Habitudes du jour</h2>
          <p className="today-empty">{habitsState.message}</p>
        </section>
      )}

      {habitsState.phase === 'ok' && habitsState.data.length > 0 && (
        <section>
          <h2 className="today-section-title">Habitudes du jour</h2>
          <ul className="today-habits-list">
            {habitsState.data.map((habit) => {
              const done = isHabitDoneForWindow(habit)
              const pending = pendingHabitIds.has(habit.id)
              return (
                <li key={habit.id} className="today-habit-item">
                  <input
                    type="checkbox"
                    checked={done}
                    disabled={pending || done}
                    onChange={() => handleHabitCheck(habit)}
                  />
                  <span className="today-habit-name">{habit.name}</span>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <section>
        <h2 className="today-section-title">Journal</h2>
        <JournalNote />
      </section>
    </div>
  )
}

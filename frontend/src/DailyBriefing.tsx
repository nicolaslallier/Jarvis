import type { BriefingState } from './useBriefing'
import type { Appointment } from './useCalendar'
import type { Task } from './useTasks'

function formatTime(a: Appointment): string {
  if (a.all_day) return 'Toute la journée'
  return new Date(a.start_time).toLocaleTimeString('fr-CA', {
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function DailyBriefing({ state }: { state: BriefingState }) {
  if (state.phase === 'loading') {
    return <p className="briefing-loading">Chargement...</p>
  }

  if (state.phase === 'error') {
    return <p className="briefing-error">Impossible de charger le résumé du jour.</p>
  }

  const { appointments, due_tasks: dueTasks, overdue_tasks: overdueTasks, summary } = state.data

  return (
    <section className="briefing">
      {summary && <p className="briefing-summary">{summary}</p>}

      {appointments.length > 0 && (
        <div className="briefing-section">
          <h3 className="briefing-section-title">Rendez-vous</h3>
          <ul className="briefing-list">
            {appointments.map((a) => (
              <li key={a.id} className="briefing-appointment">
                <span className="briefing-item-time">{formatTime(a)}</span>
                <span className="briefing-item-title">{a.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {dueTasks.length > 0 && (
        <div className="briefing-section">
          <h3 className="briefing-section-title">Tâches à faire</h3>
          <ul className="briefing-list">
            {dueTasks.map((t: Task) => (
              <li key={t.id} className="briefing-task">
                <span className="briefing-item-title">{t.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {overdueTasks.length > 0 && (
        <div className="briefing-section briefing-overdue">
          <h3 className="briefing-section-title">Tâches en retard</h3>
          <ul className="briefing-list">
            {overdueTasks.map((t: Task) => (
              <li key={t.id} className="briefing-task briefing-task-overdue">
                <span className="briefing-item-title">{t.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

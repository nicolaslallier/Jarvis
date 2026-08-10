import { useHealthPoll } from './useHealthPoll'

// Discreet nav-bar indicator (not a page section) — the detailed card this
// used to render belongs to ops, not the homepage; see docs/plan-refonte-accueil.md.
export default function HealthStatus() {
  const state = useHealthPoll()
  const isOk = state.phase === 'ok'
  const isLoading = state.phase === 'loading'

  const label = isLoading
    ? "Vérification de l'état du serveur…"
    : isOk
      ? `État : ok — base de données : ${state.data.database}`
      : `État : erreur — ${state.message}`

  return (
    <span
      className={`health-pill ${isLoading ? 'health-pill-loading' : isOk ? 'health-pill-ok' : 'health-pill-error'}`}
      title={label}
    >
      <span className="health-pill-dot" />
    </span>
  )
}

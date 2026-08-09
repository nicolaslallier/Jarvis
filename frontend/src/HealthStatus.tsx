import { useHealthPoll } from './useHealthPoll'

export default function HealthStatus() {
  const state = useHealthPoll()

  if (state.phase === 'loading') {
    return <p className="health-loading">Vérification de l'état du serveur…</p>
  }

  const isOk = state.phase === 'ok'

  return (
    <div className={`health-card ${isOk ? 'health-ok' : 'health-error'}`}>
      <div className="health-indicator">
        <span className="health-dot" />
        <strong>{isOk ? 'État : ok' : 'État : erreur'}</strong>
      </div>
      {isOk ? (
        <p>Base de données : {state.data.database}</p>
      ) : (
        <p>{state.message}</p>
      )}
      <p className="health-timestamp">
        Dernière vérification : {state.lastChecked.toLocaleTimeString()}
      </p>
    </div>
  )
}

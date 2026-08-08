import { useHealthPoll } from './useHealthPoll'

export default function HealthStatus() {
  const state = useHealthPoll()

  if (state.phase === 'loading') {
    return <p className="health-loading">Checking backend health…</p>
  }

  const isOk = state.phase === 'ok'

  return (
    <div className={`health-card ${isOk ? 'health-ok' : 'health-error'}`}>
      <div className="health-indicator">
        <span className="health-dot" />
        <strong>{isOk ? 'Status: ok' : 'Status: error'}</strong>
      </div>
      {isOk ? (
        <p>Database: {state.data.database}</p>
      ) : (
        <p>{state.message}</p>
      )}
      <p className="health-timestamp">
        Last checked: {state.lastChecked.toLocaleTimeString()}
      </p>
    </div>
  )
}

import { useSessionTimer } from './useSessionTimer'

function formatElapsed(ms: number): string {
  const secs = Math.floor(ms / 1000)
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  const s = secs % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

export default function SessionTimer() {
  const { elapsed, running, start, stop, reset } = useSessionTimer()

  return (
    <section className="session-timer">
      <time className="session-timer-display">{formatElapsed(elapsed)}</time>
      <div className="session-timer-controls">
        {!running ? (
          <button className="session-timer-btn" onClick={start}>
            {elapsed > 0 ? 'Resume' : 'Start'}
          </button>
        ) : (
          <button className="session-timer-btn" onClick={stop}>
            Stop
          </button>
        )}
        {elapsed > 0 && (
          <button className="session-timer-btn" onClick={reset}>
            Reset
          </button>
        )}
      </div>
    </section>
  )
}

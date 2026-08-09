import { useEffect, useState } from 'react'

const STORAGE_KEY = 'session-timer'

interface StoredState {
  startedAt: number | null
  running: boolean
}

function loadStored(): StoredState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw) as StoredState
  } catch {
    // corrupted — ignore
  }
  return { startedAt: null, running: false }
}

function saveStored(state: StoredState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

export function useSessionTimer() {
  const stored = loadStored()

  // Compute elapsed from persisted start time (only if we were running).
  const [elapsed, setElapsed] = useState<number>(() => {
    if (stored.startedAt && stored.running) {
      return Date.now() - stored.startedAt
    }
    return 0
  })

  const [running, setRunning] = useState(stored.running)

  // Tick every second while running.
  useEffect(() => {
    if (!running) return

    const id = setInterval(() => {
      setElapsed((prev) => {
        const start = stored.startedAt ?? Date.now() - prev
        return Date.now() - start
      })
    }, 1000)

    return () => {
      clearInterval(id)
    }
  }, [running, stored.startedAt])

  function start() {
    const startedAt = Date.now()
    saveStored({ startedAt, running: true })
    setElapsed(0)
    setRunning(true)
  }

  function stop() {
    const finalElapsed = stored.startedAt ? Date.now() - stored.startedAt : elapsed
    saveStored({ startedAt: stored.startedAt, running: false })
    setElapsed(finalElapsed)
    setRunning(false)
  }

  function reset() {
    saveStored({ startedAt: null, running: false })
    setElapsed(0)
    setRunning(false)
  }

  return { elapsed, running, start, stop, reset }
}

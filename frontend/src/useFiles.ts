import { useEffect, useState } from 'react'

export type StoredFile = {
  id: number
  filename: string
  content_type: string | null
  size: number
  created_at: string
}

type FilesState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: StoredFile[] }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

export function useFiles() {
  const [state, setState] = useState<FilesState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/files`)
        if (cancelled) return

        if (res.ok) {
          const data: StoredFile[] = await res.json()
          setState({ phase: 'ok', data })
        } else {
          setState({ phase: 'error', message: await errorMessage(res) })
        }
      } catch (err) {
        if (cancelled) return
        setState({
          phase: 'error',
          message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
        })
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  async function uploadFile(file: File): Promise<void> {
    const formData = new FormData()
    formData.append('file', file)

    const res = await fetch(`${API_URL}/files`, { method: 'POST', body: formData })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: StoredFile = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: [...prev.data, created] } : prev,
    )
  }

  async function deleteFile(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/files/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((f) => f.id !== id) } : prev,
    )
  }

  function downloadUrl(id: number): string {
    return `${API_URL}/files/${id}/download`
  }

  return { state, uploadFile, deleteFile, downloadUrl }
}

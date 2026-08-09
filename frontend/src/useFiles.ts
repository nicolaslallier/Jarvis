import { useEffect, useState } from 'react'

export type StoredFile = {
  id: number
  filename: string
  content_type: string | null
  size: number
  folder_id: number | null
  created_at: string
}

export type Folder = {
  id: number
  name: string
  parent_id: number | null
  created_at: string
}

export type Crumb = { id: number | null; name: string }

type FilesState =
  | { phase: 'loading' }
  | { phase: 'ok'; folders: Folder[]; files: StoredFile[] }
  | { phase: 'error'; message: string }

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const ROOT_CRUMB: Crumb = { id: null, name: 'Home' }

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function folderIdQuery(folderId: number | null): string {
  return folderId === null ? '' : `?parent_id=${folderId}`
}

function filesQuery(folderId: number | null): string {
  return folderId === null ? '' : `?folder_id=${folderId}`
}

export function useFiles() {
  const [breadcrumb, setBreadcrumb] = useState<Crumb[]>([ROOT_CRUMB])
  const [state, setState] = useState<FilesState>({ phase: 'loading' })

  const currentFolderId = breadcrumb[breadcrumb.length - 1].id

  async function load(folderId: number | null) {
    setState({ phase: 'loading' })
    try {
      const [foldersRes, filesRes] = await Promise.all([
        fetch(`${API_URL}/folders${folderIdQuery(folderId)}`),
        fetch(`${API_URL}/files${filesQuery(folderId)}`),
      ])

      if (!foldersRes.ok) {
        setState({ phase: 'error', message: await errorMessage(foldersRes) })
        return
      }
      if (!filesRes.ok) {
        setState({ phase: 'error', message: await errorMessage(filesRes) })
        return
      }

      const folders: Folder[] = await foldersRes.json()
      const files: StoredFile[] = await filesRes.json()
      setState({ phase: 'ok', folders, files })
    } catch (err) {
      setState({
        phase: 'error',
        message: `Network error: ${err instanceof Error ? err.message : String(err)}`,
      })
    }
  }

  useEffect(() => {
    load(currentFolderId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentFolderId])

  function openFolder(folder: Folder): void {
    setBreadcrumb((prev) => [...prev, { id: folder.id, name: folder.name }])
  }

  function goToCrumb(index: number): void {
    setBreadcrumb((prev) => prev.slice(0, index + 1))
  }

  async function createFolder(name: string): Promise<void> {
    const res = await fetch(`${API_URL}/folders`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, parent_id: currentFolderId }),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Folder = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { ...prev, folders: [...prev.folders, created] } : prev,
    )
  }

  async function deleteFolder(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/folders/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { ...prev, folders: prev.folders.filter((f) => f.id !== id) } : prev,
    )
  }

  async function uploadFile(file: File): Promise<void> {
    const formData = new FormData()
    formData.append('file', file)
    if (currentFolderId !== null) {
      formData.append('folder_id', String(currentFolderId))
    }

    const res = await fetch(`${API_URL}/files`, { method: 'POST', body: formData })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: StoredFile = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { ...prev, files: [...prev.files, created] } : prev,
    )
  }

  async function deleteFile(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/files/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { ...prev, files: prev.files.filter((f) => f.id !== id) } : prev,
    )
  }

  function downloadUrl(id: number): string {
    return `${API_URL}/files/${id}/download`
  }

  return {
    state,
    breadcrumb,
    openFolder,
    goToCrumb,
    createFolder,
    deleteFolder,
    uploadFile,
    deleteFile,
    downloadUrl,
  }
}

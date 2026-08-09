import { useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useFiles } from './useFiles'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FilesPage() {
  const { state, uploadFile, deleteFile, downloadUrl } = useFiles()
  const [uploading, setUploading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setFormError(null)
    setUploading(true)
    try {
      await uploadFile(file)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  async function handleDelete(id: number) {
    try {
      await deleteFile(id)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="files">
      <h1>Files</h1>

      <div className="files-upload">
        <input ref={inputRef} type="file" onChange={handleFileChange} disabled={uploading} />
        {uploading && <span className="files-uploading">Uploading…</span>}
        {formError && <p className="files-form-error">{formError}</p>}
      </div>

      {state.phase === 'loading' && <p className="files-loading">Loading files…</p>}
      {state.phase === 'error' && <p className="files-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <ul className="files-list">
          {state.data.length === 0 && <li className="files-empty">No files yet.</li>}
          {state.data.map((file) => (
            <li key={file.id} className="file-item">
              <div className="file-item-main">
                <a href={downloadUrl(file.id)}>{file.filename}</a>
                <span className="file-size">{formatSize(file.size)}</span>
              </div>
              <button type="button" onClick={() => handleDelete(file.id)} className="file-delete">
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

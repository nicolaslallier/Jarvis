import { useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { useFiles } from './useFiles'
import type { Folder } from './useFiles'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export default function FilesPage() {
  const {
    state,
    breadcrumb,
    openFolder,
    goToCrumb,
    createFolder,
    deleteFolder,
    uploadFile,
    deleteFile,
    downloadUrl,
  } = useFiles()
  const [uploading, setUploading] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [newFolderName, setNewFolderName] = useState('')
  const [creatingFolder, setCreatingFolder] = useState(false)
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

  async function handleCreateFolder(e: FormEvent) {
    e.preventDefault()
    const name = newFolderName.trim()
    if (!name) return

    setFormError(null)
    setCreatingFolder(true)
    try {
      await createFolder(name)
      setNewFolderName('')
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreatingFolder(false)
    }
  }

  async function handleDeleteFolder(folder: Folder) {
    if (!confirm(`Delete folder "${folder.name}" and everything inside it?`)) return
    try {
      await deleteFolder(folder.id)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
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

      <nav className="files-breadcrumb">
        {breadcrumb.map((crumb, index) => (
          <span key={crumb.id ?? 'root'}>
            {index > 0 && <span className="files-breadcrumb-sep"> / </span>}
            {index === breadcrumb.length - 1 ? (
              <span className="files-breadcrumb-current">{crumb.name}</span>
            ) : (
              <button type="button" className="files-breadcrumb-link" onClick={() => goToCrumb(index)}>
                {crumb.name}
              </button>
            )}
          </span>
        ))}
      </nav>

      <div className="files-toolbar">
        <form className="files-new-folder" onSubmit={handleCreateFolder}>
          <input
            type="text"
            placeholder="New folder name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            disabled={creatingFolder}
          />
          <button type="submit" disabled={creatingFolder || !newFolderName.trim()}>
            New folder
          </button>
        </form>

        <div className="files-upload">
          <input ref={inputRef} type="file" onChange={handleFileChange} disabled={uploading} />
          {uploading && <span className="files-uploading">Uploading…</span>}
        </div>
      </div>

      {formError && <p className="files-form-error">{formError}</p>}

      {state.phase === 'loading' && <p className="files-loading">Loading files…</p>}
      {state.phase === 'error' && <p className="files-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <ul className="files-list">
          {state.folders.length === 0 && state.files.length === 0 && (
            <li className="files-empty">This folder is empty.</li>
          )}
          {state.folders.map((folder) => (
            <li key={`folder-${folder.id}`} className="file-item folder-item">
              <div className="file-item-main">
                <button type="button" className="folder-open" onClick={() => openFolder(folder)}>
                  📁 {folder.name}
                </button>
              </div>
              <button type="button" onClick={() => handleDeleteFolder(folder)} className="file-delete">
                Delete
              </button>
            </li>
          ))}
          {state.files.map((file) => (
            <li key={`file-${file.id}`} className="file-item">
              <div className="file-item-main">
                <a href={downloadUrl(file.id)}>{file.filename}</a>
                <span className="file-size">{formatSize(file.size)}</span>
                <span className={`file-ingest-badge ${file.ingested_at ? 'is-indexed' : 'is-pending'}`}>
                  {file.ingested_at ? 'Indexed' : 'Pending'}
                </span>
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

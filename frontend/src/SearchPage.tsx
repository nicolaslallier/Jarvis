import { useState } from 'react'
import type { FormEvent } from 'react'
import { useSearch } from './useSearch'
import type { SearchResult, SearchResultKind } from './useSearch'

// Display order and French labels for each kind's section — fixed order
// regardless of which kinds actually have results, so the layout doesn't
// jump around between searches.
const SECTIONS: { kind: SearchResultKind; label: string }[] = [
  { kind: 'task', label: 'Tâches' },
  { kind: 'appointment', label: 'Rendez-vous' },
  { kind: 'file_chunk', label: 'Fichiers' },
  { kind: 'memory', label: 'Mémoire' },
  { kind: 'meeting_summary', label: 'Résumés de réunion' },
  { kind: 'chat_message', label: 'Chat' },
]

function groupByKind(results: SearchResult[]): Map<SearchResultKind, SearchResult[]> {
  const groups = new Map<SearchResultKind, SearchResult[]>()
  for (const result of results) {
    const existing = groups.get(result.kind)
    if (existing) {
      existing.push(result)
    } else {
      groups.set(result.kind, [result])
    }
  }
  return groups
}

export default function SearchPage() {
  const { state, runSearch } = useSearch()
  const [query, setQuery] = useState('')

  function handleSubmit(e: FormEvent): void {
    e.preventDefault()
    runSearch(query)
  }

  const groups = state.phase === 'ok' ? groupByKind(state.data.results) : null
  const hasAnyResults = groups !== null && groups.size > 0

  return (
    <div className="search-page">
      <h1>Recherche</h1>

      <form className="search-form" onSubmit={handleSubmit}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher dans les tâches, rendez-vous, fichiers, mémoire, chat…"
          className="search-input"
        />
        <button type="submit" disabled={state.phase === 'loading' || !query.trim()}>
          {state.phase === 'loading' ? 'Recherche…' : 'Rechercher'}
        </button>
      </form>

      {state.phase === 'error' && <p className="search-error">{state.message}</p>}

      {groups && !hasAnyResults && (
        <p className="search-empty">Aucun résultat pour « {state.phase === 'ok' ? state.data.query : query} ».</p>
      )}

      {groups &&
        SECTIONS.map(({ kind, label }) => {
          const items = groups.get(kind)
          if (!items || items.length === 0) return null
          return (
            <section className="search-section" key={kind}>
              <h2 className="search-section-title">{label}</h2>
              <ul className="search-list">
                {items.map((item) => (
                  <li key={`${item.kind}-${item.id}`} className="search-item">
                    <p className="search-item-title">{item.title}</p>
                    <p className="search-item-snippet">{item.snippet}</p>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
    </div>
  )
}

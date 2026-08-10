import { useEffect, useState } from 'react'

export type ContactDateType = 'birthday' | 'anniversary' | 'renewal' | 'autre'

export type Contact = {
  id: number
  name: string
  date: string
  date_type: string
  recurring_yearly: boolean
  reminder_lead_days: number
  created_at: string
}

type ContactsState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Contact[] }
  | { phase: 'error'; message: string }

export type NewContact = {
  name: string
  date: string
  date_type: ContactDateType
  recurring_yearly?: boolean
  reminder_lead_days?: number
}

export type ContactUpdateInput = Partial<NewContact>

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function sortByName(contacts: Contact[]): Contact[] {
  return [...contacts].sort((a, b) => a.name.localeCompare(b.name))
}

export function useContacts() {
  const [state, setState] = useState<ContactsState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/contacts`)
        if (cancelled) return

        if (res.ok) {
          const data: Contact[] = await res.json()
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

  async function createContact(input: NewContact): Promise<void> {
    const res = await fetch(`${API_URL}/contacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Contact = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: sortByName([...prev.data, created]) } : prev,
    )
  }

  async function updateContact(id: number, input: ContactUpdateInput): Promise<void> {
    const res = await fetch(`${API_URL}/contacts/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Contact = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: sortByName(prev.data.map((c) => (c.id === updated.id ? updated : c))) }
        : prev,
    )
  }

  async function deleteContact(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/contacts/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((c) => c.id !== id) } : prev,
    )
  }

  return { state, createContact, updateContact, deleteContact }
}

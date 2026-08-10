import { useEffect, useState } from 'react'

export type BillRecurrence = 'monthly' | 'yearly'

export type Bill = {
  id: number
  name: string
  amount: string
  due_day: number
  recurrence: BillRecurrence
  created_at: string
}

type BillsState =
  | { phase: 'loading' }
  | { phase: 'ok'; data: Bill[] }
  | { phase: 'error'; message: string }

export type NewBill = {
  name: string
  amount: string
  due_day: number
  recurrence: BillRecurrence
}

export type BillUpdateInput = Partial<NewBill>

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null)
  return body?.detail ?? `Backend returned ${res.status}`
}

function sortByDueDay(bills: Bill[]): Bill[] {
  return [...bills].sort((a, b) => a.due_day - b.due_day)
}

export function useBills() {
  const [state, setState] = useState<BillsState>({ phase: 'loading' })

  useEffect(() => {
    let cancelled = false

    async function load() {
      try {
        const res = await fetch(`${API_URL}/bills`)
        if (cancelled) return

        if (res.ok) {
          const data: Bill[] = await res.json()
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

  async function createBill(input: NewBill): Promise<void> {
    const res = await fetch(`${API_URL}/bills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const created: Bill = await res.json()
    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: sortByDueDay([...prev.data, created]) } : prev,
    )
  }

  async function updateBill(id: number, input: BillUpdateInput): Promise<void> {
    const res = await fetch(`${API_URL}/bills/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    const updated: Bill = await res.json()
    setState((prev) =>
      prev.phase === 'ok'
        ? { phase: 'ok', data: sortByDueDay(prev.data.map((b) => (b.id === updated.id ? updated : b))) }
        : prev,
    )
  }

  async function deleteBill(id: number): Promise<void> {
    const res = await fetch(`${API_URL}/bills/${id}`, { method: 'DELETE' })

    if (!res.ok) {
      throw new Error(await errorMessage(res))
    }

    setState((prev) =>
      prev.phase === 'ok' ? { phase: 'ok', data: prev.data.filter((b) => b.id !== id) } : prev,
    )
  }

  return { state, createBill, updateBill, deleteBill }
}

import { useState } from 'react'
import type { FormEvent } from 'react'
import { useBills } from './useBills'
import type { Bill, BillRecurrence } from './useBills'

const RECURRENCE_LABELS: Record<BillRecurrence, string> = {
  monthly: 'Mensuelle',
  yearly: 'Annuelle',
}

function formatAmount(amount: string): string {
  const value = Number(amount)
  if (Number.isNaN(value)) return `${amount} $`
  return `${value.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} $`
}

function defaultForm() {
  return { name: '', amount: '', dueDay: '1', recurrence: 'monthly' as BillRecurrence }
}

type FormState = ReturnType<typeof defaultForm>

export default function BillsPage() {
  const { state, createBill, deleteBill } = useBills()
  const [form, setForm] = useState<FormState>(defaultForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [pendingIds, setPendingIds] = useState<Set<number>>(new Set())

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)

    const dueDay = Number(form.dueDay)
    if (!Number.isInteger(dueDay) || dueDay < 1 || dueDay > 31) {
      setFormError('Le jour d’échéance doit être un nombre entre 1 et 31.')
      return
    }

    setCreating(true)
    try {
      await createBill({
        name: form.name,
        amount: form.amount,
        due_day: dueDay,
        recurrence: form.recurrence,
      })
      setForm(defaultForm())
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function handleDelete(bill: Bill) {
    if (!confirm(`Supprimer la facture « ${bill.name} » ? Cette action est définitive.`)) return
    setRowErrors((prev) => {
      const next = { ...prev }
      delete next[bill.id]
      return next
    })
    setPendingIds((prev) => new Set(prev).add(bill.id))
    deleteBill(bill.id)
      .catch((err) => {
        setRowErrors((prev) => ({ ...prev, [bill.id]: err instanceof Error ? err.message : String(err) }))
      })
      .finally(() => {
        setPendingIds((prev) => {
          const next = new Set(prev)
          next.delete(bill.id)
          return next
        })
      })
  }

  return (
    <div className="tasks">
      <h1>Factures</h1>

      <form className="tasks-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Nom de la facture"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <div className="task-edit-row">
          <input
            type="number"
            step="0.01"
            min="0"
            placeholder="Montant ($)"
            value={form.amount}
            onChange={(e) => setForm({ ...form, amount: e.target.value })}
            required
          />
          <input
            type="number"
            min={1}
            max={31}
            placeholder="Jour d’échéance"
            value={form.dueDay}
            onChange={(e) => setForm({ ...form, dueDay: e.target.value })}
            required
          />
          <select
            value={form.recurrence}
            onChange={(e) => setForm({ ...form, recurrence: e.target.value as BillRecurrence })}
          >
            {(Object.keys(RECURRENCE_LABELS) as BillRecurrence[]).map((r) => (
              <option key={r} value={r}>
                {RECURRENCE_LABELS[r]}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" disabled={creating}>
          {creating ? 'Ajout…' : 'Ajouter la facture'}
        </button>
        {formError && <p className="tasks-form-error">{formError}</p>}
      </form>

      {state.phase === 'loading' && <p className="tasks-loading">Chargement des factures…</p>}
      {state.phase === 'error' && <p className="tasks-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {state.data.length === 0 && <p className="tasks-empty">Aucune facture.</p>}
          <ul className="tasks-list">
            {state.data.map((bill) => {
              const pending = pendingIds.has(bill.id)
              return (
                <li key={bill.id} className="task-item">
                  <div className="task-item-main">
                    <strong>{bill.name}</strong>
                    <span className="task-due-date">{formatAmount(bill.amount)}</span>
                  </div>
                  <div className="task-item-meta">
                    <span className="task-badge task-status-badge">
                      Le {bill.due_day} de chaque {bill.recurrence === 'yearly' ? 'année' : 'mois'}
                    </span>
                    <span className="task-badge task-project-badge">{RECURRENCE_LABELS[bill.recurrence]}</span>
                  </div>
                  <div className="task-item-actions">
                    <button
                      type="button"
                      onClick={() => handleDelete(bill)}
                      className="task-delete"
                      disabled={pending}
                    >
                      {pending ? '…' : 'Supprimer'}
                    </button>
                  </div>
                  {rowErrors[bill.id] && <p className="tasks-row-error">{rowErrors[bill.id]}</p>}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

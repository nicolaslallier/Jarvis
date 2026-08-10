import { useState } from 'react'
import type { FormEvent } from 'react'
import { useContacts } from './useContacts'
import type { Contact, ContactDateType } from './useContacts'

// Self-contained page: styling lives in this file (not App.css) so this
// component has no dependency on the nav-wiring task that adds it to
// App.tsx/App.css — same convention as HabitsPage.tsx/BillsPage.tsx.
const STYLES = `
.contacts-page { max-width: 640px; margin: 0 auto; }
.contacts-form {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}
.contacts-form input[type="text"],
.contacts-form input[type="date"],
.contacts-form input[type="number"] {
  flex: 1 1 10rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #ccc);
}
.contacts-form select {
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #ccc);
}
.contacts-form-checkbox {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex: 0 0 auto;
}
.contacts-form button {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  border: none;
  background: #4f46e5;
  color: #fff;
  cursor: pointer;
}
.contacts-form button:disabled { opacity: 0.6; cursor: default; }
.contacts-form-error { color: #dc2626; width: 100%; margin: 0; }
.contacts-loading, .contacts-empty { opacity: 0.7; }
.contacts-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.contact-item {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  border: 1px solid var(--border-color, #ddd);
}
.contact-item-main {
  flex: 1;
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  min-width: 10rem;
}
.contact-name { font-weight: 600; }
.contact-date { font-size: 0.9rem; opacity: 0.85; }
.contact-type-badge {
  font-size: 0.75rem;
  padding: 0.1rem 0.5rem;
  border-radius: 999px;
  background: rgba(79, 70, 229, 0.12);
  color: #4f46e5;
  white-space: nowrap;
}
.contact-lead {
  font-size: 0.85rem;
  opacity: 0.75;
  white-space: nowrap;
}
.contact-delete {
  border: none;
  background: transparent;
  color: #dc2626;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
}
.contact-delete:disabled { opacity: 0.5; cursor: default; }
.contact-row-error { color: #dc2626; margin: 0.25rem 0 0 0; font-size: 0.85rem; width: 100%; }
`

const DATE_TYPE_LABELS: Record<ContactDateType, string> = {
  birthday: 'Anniversaire',
  anniversary: 'Anniversaire de couple',
  renewal: 'Renouvellement',
  autre: 'Autre',
}

function defaultCreateForm() {
  return {
    name: '',
    date: '',
    dateType: 'birthday' as ContactDateType,
    recurringYearly: true,
    reminderLeadDays: '7',
  }
}

type CreateForm = ReturnType<typeof defaultCreateForm>

function formatDate(dateStr: string): string {
  const [year, month, day] = dateStr.split('-').map(Number)
  if (!year || !month || !day) return dateStr
  return new Date(year, month - 1, day).toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

export default function ContactsPage() {
  const { state, createContact, deleteContact } = useContacts()

  const [form, setForm] = useState<CreateForm>(defaultCreateForm)
  const [formError, setFormError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const [rowErrors, setRowErrors] = useState<Record<number, string>>({})
  const [pendingIds, setPendingIds] = useState<Set<number>>(new Set())

  function runRowAction(id: number, action: () => Promise<void>) {
    setRowErrors((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    setPendingIds((prev) => new Set(prev).add(id))
    action()
      .catch((err) => {
        setRowErrors((prev) => ({ ...prev, [id]: err instanceof Error ? err.message : String(err) }))
      })
      .finally(() => {
        setPendingIds((prev) => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      })
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)

    const name = form.name.trim()
    if (!name || !form.date) return

    const leadDays = Number(form.reminderLeadDays)
    if (!Number.isInteger(leadDays) || leadDays < 0) {
      setFormError('Le délai de rappel doit être un nombre de jours positif.')
      return
    }

    setCreating(true)
    try {
      await createContact({
        name,
        date: form.date,
        date_type: form.dateType,
        recurring_yearly: form.recurringYearly,
        reminder_lead_days: leadDays,
      })
      setForm(defaultCreateForm())
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setCreating(false)
    }
  }

  function handleDelete(contact: Contact) {
    if (!window.confirm(`Supprimer le contact « ${contact.name} » ? Cette action est définitive.`)) return
    runRowAction(contact.id, () => deleteContact(contact.id))
  }

  function renderContact(contact: Contact) {
    const pending = pendingIds.has(contact.id)
    const label = DATE_TYPE_LABELS[contact.date_type as ContactDateType] ?? contact.date_type

    return (
      <li key={contact.id} className="contact-item">
        <div className="contact-item-main">
          <span className="contact-name">{contact.name}</span>
          <span className="contact-date">{formatDate(contact.date)}</span>
        </div>
        <span className="contact-type-badge">{label}</span>
        <span className="contact-lead">
          Rappel {contact.reminder_lead_days} j avant
          {contact.recurring_yearly ? ' · récurrent' : ''}
        </span>
        <button
          type="button"
          className="contact-delete"
          onClick={() => handleDelete(contact)}
          disabled={pending}
        >
          {pending ? '…' : 'Supprimer'}
        </button>
        {rowErrors[contact.id] && <p className="contact-row-error">{rowErrors[contact.id]}</p>}
      </li>
    )
  }

  return (
    <div className="contacts-page">
      <style>{STYLES}</style>
      <h1>Contacts</h1>

      <form className="contacts-form" onSubmit={handleSubmit}>
        <input
          type="text"
          placeholder="Nom"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />
        <input
          type="date"
          value={form.date}
          onChange={(e) => setForm({ ...form, date: e.target.value })}
          required
        />
        <select
          value={form.dateType}
          onChange={(e) => setForm({ ...form, dateType: e.target.value as ContactDateType })}
        >
          {(Object.keys(DATE_TYPE_LABELS) as ContactDateType[]).map((t) => (
            <option key={t} value={t}>
              {DATE_TYPE_LABELS[t]}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          placeholder="Délai de rappel (jours)"
          value={form.reminderLeadDays}
          onChange={(e) => setForm({ ...form, reminderLeadDays: e.target.value })}
          required
        />
        <label className="contacts-form-checkbox">
          <input
            type="checkbox"
            checked={form.recurringYearly}
            onChange={(e) => setForm({ ...form, recurringYearly: e.target.checked })}
          />
          Récurrent chaque année
        </label>
        <button type="submit" disabled={creating || !form.name.trim() || !form.date}>
          {creating ? 'Ajout…' : 'Ajouter'}
        </button>
        {formError && <p className="contacts-form-error">{formError}</p>}
      </form>

      {state.phase === 'loading' && <p className="contacts-loading">Chargement des contacts…</p>}
      {state.phase === 'error' && <p className="contacts-form-error">{state.message}</p>}
      {state.phase === 'ok' && (
        <>
          {state.data.length === 0 && <p className="contacts-empty">Aucun contact pour l'instant.</p>}
          {state.data.length > 0 && <ul className="contacts-list">{state.data.map(renderContact)}</ul>}
        </>
      )}
    </div>
  )
}

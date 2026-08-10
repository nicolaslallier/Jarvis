import { NavLink, Route, Routes } from 'react-router-dom'
import TasksPage from './TasksPage'
import ChatPage from './ChatPage'
import FilesPage from './FilesPage'
import CalendarPage from './CalendarPage'
import MemoryPage from './MemoryPage'
import TodayPage from './TodayPage'
import SearchPage from './SearchPage'
import HabitsPage from './HabitsPage'
import ContactsPage from './ContactsPage'
import BillsPage from './BillsPage'
import MeetingSummariesPage from './MeetingSummariesPage'
import HealthStatus from './HealthStatus'
import './App.css'

function App() {
  return (
    <main className="app">
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Accueil
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Tâches
        </NavLink>
        <NavLink to="/calendar" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Calendrier
        </NavLink>
        <NavLink to="/habits" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Habitudes
        </NavLink>
        <NavLink to="/contacts" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Contacts
        </NavLink>
        <NavLink to="/bills" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Factures
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Chat
        </NavLink>
        <NavLink to="/search" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Recherche
        </NavLink>
        <NavLink to="/files" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Fichiers
        </NavLink>
        <NavLink to="/memory" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Mémoire
        </NavLink>
        <NavLink
          to="/meeting-summaries"
          className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}
        >
          Résumés de réunion
        </NavLink>
        <HealthStatus />
      </nav>
      <Routes>
        <Route path="/" element={<TodayPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/habits" element={<HabitsPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/bills" element={<BillsPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/files" element={<FilesPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/meeting-summaries" element={<MeetingSummariesPage />} />
      </Routes>
    </main>
  )
}

export default App

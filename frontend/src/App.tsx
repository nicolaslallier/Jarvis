import { NavLink, Route, Routes } from 'react-router-dom'
import HealthStatus from './HealthStatus'
import SessionTimer from './SessionTimer'
import TaskCountWidget from './TaskCountWidget'
import TasksPage from './TasksPage'
import ChatPage from './ChatPage'
import FilesPage from './FilesPage'
import CalendarPage from './CalendarPage'
import './App.css'

function App() {
  return (
    <main className="app">
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Home
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Tâches
        </NavLink>
        <NavLink to="/calendar" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Calendar
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Chat
        </NavLink>
        <NavLink to="/files" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Files
        </NavLink>
      </nav>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <h1>Jarvis Portal</h1>
              <SessionTimer />
              <TaskCountWidget />
              <HealthStatus />
            </>
          }
        />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/files" element={<FilesPage />} />
      </Routes>
    </main>
  )
}

export default App

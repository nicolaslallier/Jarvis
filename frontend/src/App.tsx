import { NavLink, Route, Routes } from 'react-router-dom'
import HealthStatus from './HealthStatus'
import TasksPage from './TasksPage'
import ChatPage from './ChatPage'
import './App.css'

function App() {
  return (
    <main className="app">
      <nav className="nav">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Home
        </NavLink>
        <NavLink to="/tasks" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Tasks
        </NavLink>
        <NavLink to="/chat" className={({ isActive }) => (isActive ? 'nav-link-active' : 'nav-link')}>
          Chat
        </NavLink>
      </nav>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <h1>Jarvis Portal</h1>
              <HealthStatus />
            </>
          }
        />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/chat" element={<ChatPage />} />
      </Routes>
    </main>
  )
}

export default App

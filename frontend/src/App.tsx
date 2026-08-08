import { NavLink, Route, Routes } from 'react-router-dom'
import HealthStatus from './HealthStatus'
import TasksPage from './TasksPage'
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
      </Routes>
    </main>
  )
}

export default App

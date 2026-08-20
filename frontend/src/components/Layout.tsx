/** App shell: sidebar navigation, top bar, toasts. */
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/auth'
import { Toasts } from './Ui'

function Logo() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M7 3c0 6 10 6 10 12s-10 6-10 6" stroke="#4f8ef7" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M17 3c0 6-10 6-10 12s10 6 10 6" stroke="#a371f7" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M9 7h6M8.4 11h7.2M8.4 15h7.2M9 19h6" stroke="#5bc0a8" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  )
}

export default function Layout() {
  const { user, capabilities, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            GeneForge
            <div className="v">v{capabilities?.version ?? '0.1.0'}</div>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            <span>◧</span> <span>Dashboard</span>
          </NavLink>
          <NavLink to="/projects">
            <span>▤</span> <span>Projects</span>
          </NavLink>
          <NavLink to="/jobs">
            <span>◷</span> <span>Jobs</span>
          </NavLink>
          <NavLink to="/tools">
            <span>⚙</span> <span>Tool bench</span>
          </NavLink>
          <div className="group">Reference</div>
          <NavLink to="/enzymes">
            <span>✂</span> <span>Enzyme catalogue</span>
          </NavLink>
          <NavLink to="/external">
            <span>⇗</span> <span>External databases</span>
          </NavLink>
          {user?.role === 'admin' && (
            <>
              <div className="group">Administration</div>
              <NavLink to="/admin">
                <span>⚿</span> <span>Users & audit</span>
              </NavLink>
            </>
          )}
          <div className="group">Help</div>
          <a href="/docs" target="_blank" rel="noreferrer">
            <span>◈</span> <span>API documentation</span>
          </a>
        </nav>
        <div className="sidebar-footer">
          <div className="truncate" title={user?.email}>
            {user?.username} · <span className="dim">{user?.role}</span>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <button
              className="ghost sm"
              onClick={() => {
                logout()
                navigate('/login')
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <Outlet />
      </div>
      <Toasts />
    </div>
  )
}

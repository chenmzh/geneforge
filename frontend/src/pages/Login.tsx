/** Login / registration screen. */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/store/auth'
import { Toasts } from '@/components/Ui'

export default function Login() {
  const { login, register, capabilities } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState<'login' | 'register'>('login')
  const [form, setForm] = useState({ username: '', password: '', email: '', full_name: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (tab === 'login') await login(form.username, form.password)
      else
        await register({
          email: form.email,
          username: form.username,
          password: form.password,
          full_name: form.full_name || undefined,
        })
      navigate('/')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login">
        <div className="card">
          <div className="body">
            <div>
              <h2>GeneForge</h2>
              <p className="small muted" style={{ margin: 0 }}>
                DNA & plasmid workbench — visualise, edit, digest, design and align.
              </p>
            </div>
            <div className="tabs" style={{ marginTop: 4 }}>
              <button className={tab === 'login' ? 'active' : ''} onClick={() => setTab('login')} type="button">
                Sign in
              </button>
              {capabilities?.registration_open !== false && (
                <button className={tab === 'register' ? 'active' : ''} onClick={() => setTab('register')} type="button">
                  Create account
                </button>
              )}
            </div>
            <form onSubmit={submit} className="col">
              {tab === 'register' && (
                <>
                  <label className="field">
                    Email
                    <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                  </label>
                  <label className="field">
                    Full name (optional)
                    <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
                  </label>
                </>
              )}
              <label className="field">
                {tab === 'login' ? 'Username or email' : 'Username'}
                <input
                  required
                  autoFocus
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  placeholder={tab === 'login' ? 'admin@geneforge.local' : 'jdoe'}
                />
              </label>
              <label className="field">
                Password
                <input
                  type="password"
                  required
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
              </label>
              {error && <div className="tag err">{error}</div>}
              <button className="primary" type="submit" disabled={busy}>
                {busy ? 'Please wait…' : tab === 'login' ? 'Sign in' : 'Create account and sign in'}
              </button>
            </form>
            <p className="tiny dim" style={{ margin: 0 }}>
              First run? The bootstrap administrator is <span className="mono">admin@geneforge.local</span> with the
              password from <span className="mono">FIRST_SUPERUSER_PASSWORD</span> — change it immediately.
            </p>
          </div>
        </div>
      </div>
      <Toasts />
    </div>
  )
}

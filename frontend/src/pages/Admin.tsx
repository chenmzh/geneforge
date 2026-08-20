/** Admin: user management, API keys and the audit trail. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { User } from '@/api/types'
import { Empty, Modal, Spinner } from '@/components/Ui'
import { reportError, useUi } from '@/store/auth'

export default function Admin() {
  const qc = useQueryClient()
  const notify = useUi((s) => s.notify)
  const [tab, setTab] = useState<'users' | 'audit' | 'keys'>('users')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ email: '', username: '', password: '', role: 'editor', full_name: '' })
  const [keyName, setKeyName] = useState('')
  const [issued, setIssued] = useState<string | null>(null)

  const users = useQuery({ queryKey: ['users'], queryFn: () => api.users(), enabled: tab === 'users' })
  const audit = useQuery({ queryKey: ['audit'], queryFn: () => api.auditLogs(150), enabled: tab === 'audit' })
  const keys = useQuery({ queryKey: ['api-keys'], queryFn: api.apiKeys, enabled: tab === 'keys' })
  const stats = useQuery({ queryKey: ['instance-stats'], queryFn: api.instanceStats })

  const create = useMutation<User, Error, void>({
    mutationFn: () => api.createUser(draft),
    onSuccess: () => {
      notify('User created', 'success')
      setCreating(false)
      setDraft({ email: '', username: '', password: '', role: 'editor', full_name: '' })
      void qc.invalidateQueries({ queryKey: ['users'] })
    },
    onError: (e) => reportError(e),
  })

  return (
    <>
      <div className="topbar">
        <h1>Administration</h1>
        <span className="spacer" />
        {stats.data && (
          <span className="dim tiny">
            {String(stats.data.users)} users · {String(stats.data.projects)} projects · {String(stats.data.sequences)} sequences ·{' '}
            {Number(stats.data.total_base_pairs).toLocaleString()} bp
          </span>
        )}
      </div>
      <div className="content">
        <div className="tabs" style={{ marginBottom: 12 }}>
          <button className={tab === 'users' ? 'active' : ''} onClick={() => setTab('users')}>
            Users
          </button>
          <button className={tab === 'keys' ? 'active' : ''} onClick={() => setTab('keys')}>
            My API keys
          </button>
          <button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}>
            Audit trail
          </button>
        </div>

        {tab === 'users' && (
          <div className="card">
            <header>
              Users
              <span className="spacer" />
              <button className="sm primary" onClick={() => setCreating(true)}>
                + new user
              </button>
            </header>
            <div className="body">
              {users.isLoading && <Spinner />}
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Email</th>
                    <th>Role</th>
                    <th>Active</th>
                    <th>Last login</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.data?.items.map((u) => (
                    <tr key={u.id}>
                      <td>{u.username}</td>
                      <td className="tiny">{u.email}</td>
                      <td>
                        <select
                          value={u.role}
                          onChange={async (e) => {
                            await api.updateUser(u.id, { role: e.target.value }).catch(reportError)
                            void qc.invalidateQueries({ queryKey: ['users'] })
                          }}
                          style={{ width: 110 }}
                        >
                          <option value="admin">admin</option>
                          <option value="editor">editor</option>
                          <option value="viewer">viewer</option>
                        </select>
                      </td>
                      <td>{u.is_active ? <span className="tag ok">yes</span> : <span className="tag err">no</span>}</td>
                      <td className="tiny dim">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</td>
                      <td className="right">
                        <button
                          className="ghost sm"
                          onClick={async () => {
                            await api.updateUser(u.id, { is_active: !u.is_active }).catch(reportError)
                            void qc.invalidateQueries({ queryKey: ['users'] })
                          }}
                        >
                          {u.is_active ? 'disable' : 'enable'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {tab === 'keys' && (
          <div className="card">
            <header>API keys</header>
            <div className="body col">
              <p className="small muted" style={{ marginTop: 0 }}>
                Use an API key with the <span className="mono">X-API-Key</span> header for scripted pipelines and LIMS
                integrations. The key is shown once.
              </p>
              <div className="row">
                <input placeholder="Key name (e.g. nextflow-pipeline)" value={keyName} onChange={(e) => setKeyName(e.target.value)} style={{ maxWidth: 300 }} />
                <button
                  className="primary"
                  disabled={!keyName}
                  onClick={async () => {
                    try {
                      const res = await api.createApiKey(keyName, 365)
                      setIssued(res.key)
                      setKeyName('')
                      void qc.invalidateQueries({ queryKey: ['api-keys'] })
                    } catch (e) {
                      reportError(e)
                    }
                  }}
                >
                  create key
                </button>
              </div>
              {issued && (
                <div className="col">
                  <span className="tag warn">Copy this now — it will not be shown again</span>
                  <code className="mono small" style={{ wordBreak: 'break-all' }}>
                    {issued}
                  </code>
                </div>
              )}
              {keys.data?.length === 0 && <Empty>No keys yet.</Empty>}
              {(keys.data?.length ?? 0) > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Prefix</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {keys.data?.map((k) => (
                      <tr key={k.id}>
                        <td>{k.name}</td>
                        <td className="mono tiny">{k.prefix}</td>
                        <td>{k.is_active ? <span className="tag ok">active</span> : <span className="tag">revoked</span>}</td>
                        <td className="tiny dim">{new Date(k.created_at).toLocaleString()}</td>
                        <td className="right">
                          {k.is_active && (
                            <button
                              className="ghost sm"
                              onClick={async () => {
                                await api.revokeApiKey(k.id).catch(reportError)
                                void qc.invalidateQueries({ queryKey: ['api-keys'] })
                              }}
                            >
                              revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {tab === 'audit' && (
          <div className="card">
            <header>Audit trail</header>
            <div className="body">
              {audit.isLoading && <Spinner />}
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Action</th>
                    <th>Entity</th>
                    <th>IP</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.data?.items.map((a) => (
                    <tr key={a.id}>
                      <td className="tiny nowrap">{new Date(a.created_at).toLocaleString()}</td>
                      <td className="tiny">{a.action}</td>
                      <td className="tiny dim">
                        {a.entity_type}
                        {a.entity_id ? ` · ${a.entity_id.slice(0, 8)}` : ''}
                      </td>
                      <td className="tiny dim">{a.ip_address ?? '—'}</td>
                      <td className="tiny dim truncate" style={{ maxWidth: 320 }}>
                        {JSON.stringify(a.detail)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {creating && (
        <Modal
          title="Create user"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button onClick={() => setCreating(false)}>Cancel</button>
              <button className="primary" onClick={() => create.mutate()} disabled={create.isPending}>
                Create
              </button>
            </>
          }
        >
          <div className="grid cols-2">
            <label className="field">
              Email
              <input value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} />
            </label>
            <label className="field">
              Username
              <input value={draft.username} onChange={(e) => setDraft({ ...draft, username: e.target.value })} />
            </label>
            <label className="field">
              Password
              <input type="password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} />
            </label>
            <label className="field">
              Role
              <select value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
                <option value="admin">admin</option>
                <option value="editor">editor</option>
                <option value="viewer">viewer</option>
              </select>
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}

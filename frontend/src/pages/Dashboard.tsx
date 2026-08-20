/** Dashboard: instance capabilities, quick stats and recent constructs. */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import { Spinner, Stat } from '@/components/Ui'
import { formatBp } from '@/lib/seq'
import { useAuth } from '@/store/auth'

export default function Dashboard() {
  const { user, capabilities } = useAuth()
  const summary = useQuery({ queryKey: ['summary'], queryFn: api.summary })
  const projects = useQuery({ queryKey: ['projects', ''], queryFn: () => api.projects() })

  return (
    <>
      <div className="topbar">
        <h1>Dashboard</h1>
        <span className="spacer" />
        <Link className="btn primary" to="/projects">
          New project
        </Link>
      </div>
      <div className="content">
        <div className="grid cols-4" style={{ marginBottom: 16 }}>
          <div className="card">
            <div className="body">
              <Stat label="Projects" value={summary.data?.projects ?? '—'} />
            </div>
          </div>
          <div className="card">
            <div className="body">
              <Stat label="Sequences" value={summary.data?.sequences ?? '—'} />
            </div>
          </div>
          <div className="card">
            <div className="body">
              <Stat label="Active jobs" value={summary.data?.active_jobs ?? '—'} />
            </div>
          </div>
          <div className="card">
            <div className="body">
              <Stat label="Enzymes" value={capabilities?.enzyme_catalogue_size ?? '—'} hint="Restriction enzymes in the catalogue" />
            </div>
          </div>
        </div>

        <div className="grid cols-2">
          <div className="card">
            <header>Recently updated constructs</header>
            <div className="body">
              {summary.isLoading && <Spinner />}
              {summary.data?.recent_sequences.length === 0 && (
                <p className="muted small" style={{ margin: 0 }}>
                  Nothing yet — create a project and import a GenBank or FASTA file.
                </p>
              )}
              <div className="split-list">
                {summary.data?.recent_sequences.map((s) => (
                  <Link className="list-item" key={s.id} to={`/sequences/${s.id}`}>
                    <div className="grow">
                      <div className="title truncate">{s.name}</div>
                      <div className="tiny dim">
                        {formatBp(s.length)} · {s.topology}
                        {s.updated_at ? ` · ${new Date(s.updated_at).toLocaleString()}` : ''}
                      </div>
                    </div>
                    <span className="tag">open</span>
                  </Link>
                ))}
              </div>
            </div>
          </div>

          <div className="card">
            <header>Your projects</header>
            <div className="body">
              {projects.isLoading && <Spinner />}
              <div className="split-list">
                {projects.data?.items.map((p) => (
                  <Link className="list-item" key={p.id} to={`/projects/${p.id}`}>
                    <div className="grow">
                      <div className="title truncate">{p.name}</div>
                      <div className="tiny dim">
                        {p.sequence_count} sequences · your role: {p.my_role}
                      </div>
                    </div>
                    {p.tags.slice(0, 2).map((t) => (
                      <span className="tag" key={t}>
                        {t}
                      </span>
                    ))}
                  </Link>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginTop: 16 }}>
          <header>Deployment</header>
          <div className="body">
            <dl className="kv">
              <dt>Signed in as</dt>
              <dd>
                {user?.username} ({user?.role})
              </dd>
              <dt>Environment</dt>
              <dd>{capabilities?.environment}</dd>
              <dt>Task queue</dt>
              <dd>{capabilities?.queue_backend}</dd>
              <dt>Import formats</dt>
              <dd>{capabilities?.import_formats.join(', ')}</dd>
              <dt>Export formats</dt>
              <dd>{capabilities?.export_formats.join(', ')}</dd>
              <dt>Max sequence</dt>
              <dd>{capabilities ? formatBp(capabilities.max_sequence_length) : '—'}</dd>
              <dt>External proxy</dt>
              <dd>{capabilities?.external_proxy_enabled ? 'enabled (allow-listed hosts)' : 'disabled'}</dd>
            </dl>
            <p className="tiny dim" style={{ marginBottom: 0 }}>
              Interactive API reference: <a href="/docs" target="_blank" rel="noreferrer">/docs</a> ·{' '}
              <a href="/redoc" target="_blank" rel="noreferrer">/redoc</a> ·{' '}
              <a href="/openapi.json" target="_blank" rel="noreferrer">OpenAPI schema</a>
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

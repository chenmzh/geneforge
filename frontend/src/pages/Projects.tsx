/** Project list + creation. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '@/api/client'
import type { Project } from '@/api/types'
import { Empty, Modal, Spinner } from '@/components/Ui'
import { reportError, useUi } from '@/store/auth'

export default function Projects() {
  const qc = useQueryClient()
  const notify = useUi((s) => s.notify)
  const [search, setSearch] = useState('')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ name: '', description: '', tags: '' })

  const projects = useQuery({ queryKey: ['projects', search], queryFn: () => api.projects(search) })

  const create = useMutation<Project, Error, void>({
    mutationFn: () =>
      api.createProject({
        name: draft.name,
        description: draft.description || undefined,
        tags: draft.tags ? draft.tags.split(',').map((t) => t.trim()).filter(Boolean) : [],
      }),
    onSuccess: () => {
      notify('Project created', 'success')
      setCreating(false)
      setDraft({ name: '', description: '', tags: '' })
      void qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: (e) => reportError(e),
  })

  return (
    <>
      <div className="topbar">
        <h1>Projects</h1>
        <span className="spacer" />
        <input
          placeholder="Search projects…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ width: 240 }}
        />
        <button className="primary" onClick={() => setCreating(true)}>
          + New project
        </button>
      </div>
      <div className="content">
        {projects.isLoading && <Spinner />}
        {projects.data?.items.length === 0 && <Empty>No projects yet. Create one to start importing constructs.</Empty>}
        <div className="grid cols-3">
          {projects.data?.items.map((p) => (
            <Link className="card" key={p.id} to={`/projects/${p.id}`} style={{ textDecoration: 'none', color: 'inherit' }}>
              <header>
                <span className="truncate">{p.name}</span>
                <span className="spacer" />
                <span className="tag">{p.my_role}</span>
              </header>
              <div className="body">
                <p className="small muted" style={{ marginTop: 0, minHeight: 34 }}>
                  {p.description || <span className="dim">No description</span>}
                </p>
                <div className="row small">
                  <span>{p.sequence_count} sequences</span>
                  <span className="spacer" style={{ flex: 1 }} />
                  <span className="dim tiny">{new Date(p.updated_at).toLocaleDateString()}</span>
                </div>
                {p.tags.length > 0 && (
                  <div className="row" style={{ marginTop: 8 }}>
                    {p.tags.map((t) => (
                      <span className="tag" key={t}>
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </Link>
          ))}
        </div>
      </div>

      {creating && (
        <Modal
          title="New project"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button onClick={() => setCreating(false)}>Cancel</button>
              <button className="primary" onClick={() => create.mutate()} disabled={!draft.name || create.isPending}>
                Create
              </button>
            </>
          }
        >
          <div className="col">
            <label className="field">
              Name
              <input autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="CRISPR knock-in vectors" />
            </label>
            <label className="field">
              Description
              <textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} style={{ minHeight: 70 }} />
            </label>
            <label className="field">
              Tags (comma separated)
              <input value={draft.tags} onChange={(e) => setDraft({ ...draft, tags: e.target.value })} placeholder="cloning, 2026" />
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}

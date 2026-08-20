/** External database registry: browse, render links, fetch + import, admin CRUD. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ExternalResource } from '@/api/types'
import { Empty, Modal, Spinner } from '@/components/Ui'
import { reportError, useAuth, useUi } from '@/store/auth'

function templateFields(template: string): string[] {
  return Array.from(template.matchAll(/\{(\w+)\}/g)).map((m) => m[1])
}

export default function External() {
  const qc = useQueryClient()
  const notify = useUi((s) => s.notify)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [active, setActive] = useState<ExternalResource | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  const [importTo, setImportTo] = useState('')
  const [preview, setPreview] = useState<string>('')
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ name: '', kind: 'link', url_template: '', description: '', allow_proxy: false })

  const resources = useQuery({ queryKey: ['external'], queryFn: api.externalResources })
  const projects = useQuery({ queryKey: ['projects', ''], queryFn: () => api.projects() })
  const policy = useQuery({ queryKey: ['proxy-policy'], queryFn: api.proxyPolicy })

  const open = (resource: ExternalResource) => {
    setActive(resource)
    const initial: Record<string, string> = {}
    for (const field of templateFields(resource.url_template)) {
      initial[field] = String((resource.query_defaults as Record<string, unknown>)[field] ?? '')
    }
    setParams(initial)
    setPreview('')
  }

  const renderLink = async () => {
    if (!active) return
    try {
      const res = await api.renderExternalUrl(active.id, params)
      window.open(res.url, '_blank', 'noopener')
    } catch (e) {
      reportError(e)
    }
  }

  const fetchRecord = async () => {
    if (!active) return
    try {
      const res = await api.fetchExternal(active.id, params, importTo || undefined, true)
      setPreview(res.preview)
      if (res.imported.length) {
        notify(`Imported ${res.imported.length} record(s): ${res.imported.map((r) => r.name).join(', ')}`, 'success')
        void qc.invalidateQueries({ queryKey: ['sequences'] })
      } else {
        notify(`Fetched ${res.detected_format} (${res.url})`, 'success')
      }
    } catch (e) {
      reportError(e)
    }
  }

  const create = useMutation<ExternalResource, Error, void>({
    mutationFn: () => api.createExternalResource(draft),
    onSuccess: () => {
      notify('Resource registered', 'success')
      setCreating(false)
      setDraft({ name: '', kind: 'link', url_template: '', description: '', allow_proxy: false })
      void qc.invalidateQueries({ queryKey: ['external'] })
    },
    onError: (e) => reportError(e),
  })

  return (
    <>
      <div className="topbar">
        <h1>External databases & APIs</h1>
        <span className="spacer" />
        {isAdmin && (
          <button className="primary" onClick={() => setCreating(true)}>
            + Register resource
          </button>
        )}
      </div>
      <div className="content">
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="body small muted">
            <p style={{ marginTop: 0 }}>
              <b>link</b> resources open a URL in a new tab. <b>rest</b> resources are fetched by the server so results
              can be imported straight into a project — only hosts on the allow-list may be contacted, and private
              address space is refused.
            </p>
            <div className="row tiny">
              <span className={`tag ${policy.data?.enabled ? 'ok' : 'warn'}`}>
                proxy {policy.data?.enabled ? 'enabled' : 'disabled'}
              </span>
              {policy.data?.allowlist.map((host) => (
                <span className="tag" key={host}>
                  {host}
                </span>
              ))}
            </div>
          </div>
        </div>

        {resources.isLoading && <Spinner />}
        {resources.data?.length === 0 && <Empty>No resources registered.</Empty>}
        <div className="grid cols-3">
          {resources.data?.map((r) => (
            <div className="card" key={r.id}>
              <header>
                <span className="truncate">{r.name}</span>
                <span className="spacer" />
                <span className="tag">{r.kind}</span>
              </header>
              <div className="body col">
                <p className="small muted" style={{ margin: 0, minHeight: 32 }}>
                  {r.description || <span className="dim">—</span>}
                </p>
                <code className="tiny dim" style={{ wordBreak: 'break-all' }}>
                  {r.url_template}
                </code>
                <div className="row">
                  <button className="sm" onClick={() => open(r)}>
                    use
                  </button>
                  {!r.is_enabled && <span className="tag warn">disabled</span>}
                  {r.allow_proxy && <span className="tag info">server-fetch</span>}
                  {isAdmin && (
                    <button
                      className="ghost sm"
                      onClick={async () => {
                        if (!confirm(`Delete resource “${r.name}”?`)) return
                        await api.deleteExternalResource(r.id).catch(reportError)
                        void qc.invalidateQueries({ queryKey: ['external'] })
                      }}
                    >
                      🗑
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {active && (
        <Modal
          title={active.name}
          onClose={() => setActive(null)}
          footer={
            <>
              <button onClick={() => setActive(null)}>Close</button>
              <button onClick={renderLink}>Open in new tab</button>
              {active.allow_proxy && (
                <button className="primary" onClick={fetchRecord}>
                  Fetch{importTo ? ' & import' : ''}
                </button>
              )}
            </>
          }
        >
          <div className="col">
            {templateFields(active.url_template).map((field) => (
              <label className="field" key={field}>
                {field}
                <input value={params[field] ?? ''} onChange={(e) => setParams({ ...params, [field]: e.target.value })} />
              </label>
            ))}
            {active.allow_proxy && (
              <label className="field">
                Import into project (optional)
                <select value={importTo} onChange={(e) => setImportTo(e.target.value)}>
                  <option value="">— don’t import, just preview —</option>
                  {projects.data?.items.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {preview && (
              <label className="field">
                Response preview
                <textarea readOnly value={preview} style={{ minHeight: 180 }} />
              </label>
            )}
          </div>
        </Modal>
      )}

      {creating && (
        <Modal
          title="Register external resource"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button onClick={() => setCreating(false)}>Cancel</button>
              <button className="primary" onClick={() => create.mutate()} disabled={!draft.name || !draft.url_template}>
                Register
              </button>
            </>
          }
        >
          <div className="col">
            <label className="field">
              Name
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Internal LIMS lookup" />
            </label>
            <label className="field">
              Kind
              <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
                <option value="link">link (open in browser)</option>
                <option value="rest">rest (server fetch + import)</option>
                <option value="blast">blast (external search)</option>
              </select>
            </label>
            <label className="field">
              URL template — use <span className="mono">{'{placeholders}'}</span>
              <input
                value={draft.url_template}
                onChange={(e) => setDraft({ ...draft, url_template: e.target.value })}
                placeholder="https://lims.example.org/api/plasmid/{id}?format=genbank"
              />
            </label>
            <label className="field">
              Description
              <input value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
            </label>
            <label className="inline">
              <input type="checkbox" checked={draft.allow_proxy} onChange={(e) => setDraft({ ...draft, allow_proxy: e.target.checked })} />
              allow server-side fetching (host must also be on EXTERNAL_PROXY_ALLOWLIST)
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}

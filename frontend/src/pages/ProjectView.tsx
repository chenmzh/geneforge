/** One project: sequence list, import (file / paste / URL), members, new construct. */
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { ImportResult, SequenceDetail } from '@/api/types'
import { Empty, Modal, Spinner } from '@/components/Ui'
import { formatBp, formatNumber } from '@/lib/seq'
import { reportError, useUi } from '@/store/auth'

export default function ProjectView() {
  const { projectId = '' } = useParams()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const notify = useUi((s) => s.notify)
  const fileRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [memberOpen, setMemberOpen] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteUrl, setPasteUrl] = useState('')
  const [autoAnnotate, setAutoAnnotate] = useState(true)
  const [draft, setDraft] = useState({ name: '', sequence: '', topology: 'linear' as 'linear' | 'circular' })
  const [member, setMember] = useState({ username: '', role: 'viewer' })

  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.project(projectId) })
  const sequences = useQuery({
    queryKey: ['sequences', projectId, search],
    queryFn: () => api.sequences(projectId, search),
  })

  const canEdit = project.data?.my_role === 'owner' || project.data?.my_role === 'editor'

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['sequences', projectId] })
    void qc.invalidateQueries({ queryKey: ['project', projectId] })
    void qc.invalidateQueries({ queryKey: ['summary'] })
  }

  const uploadFiles = async (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      try {
        const res = await api.importFile(projectId, file, autoAnnotate)
        notify(`${file.name}: imported ${res.imported.length} record(s) as ${res.detected_format}`, 'success')
        if (res.skipped.length) notify(`${res.skipped.length} record(s) skipped`, 'error')
      } catch (e) {
        reportError(e)
      }
    }
    setImportOpen(false)
    refresh()
  }

  const importText = useMutation<ImportResult, Error, void>({
    mutationFn: () =>
      api.importText(projectId, {
        content: pasteText || undefined,
        url: pasteUrl || undefined,
        auto_annotate: autoAnnotate,
      }),
    onSuccess: (res) => {
      notify(`Imported ${res.imported.length} record(s) (${res.detected_format})`, 'success')
      setImportOpen(false)
      setPasteText('')
      setPasteUrl('')
      refresh()
    },
    onError: (e) => reportError(e),
  })

  const createSequence = useMutation<SequenceDetail, Error, void>({
    mutationFn: () =>
      api.createSequence(projectId, {
        name: draft.name,
        sequence: draft.sequence.replace(/[^A-Za-z]/g, ''),
        topology: draft.topology,
        auto_annotate: autoAnnotate,
      }),
    onSuccess: (seq) => {
      notify('Construct created', 'success')
      setNewOpen(false)
      refresh()
      navigate(`/sequences/${seq.id}`)
    },
    onError: (e) => reportError(e),
  })

  const addMember = useMutation<{ id: string; user_id: string; role: string }, Error, void>({
    mutationFn: () => api.addMember(projectId, { username: member.username, role: member.role }),
    onSuccess: () => {
      notify('Member added', 'success')
      setMemberOpen(false)
      void qc.invalidateQueries({ queryKey: ['project', projectId] })
    },
    onError: (e) => reportError(e),
  })

  return (
    <>
      <div className="topbar">
        <Link to="/projects" className="dim">
          ← Projects
        </Link>
        <h1>{project.data?.name ?? '…'}</h1>
        {project.data && <span className="tag">{project.data.my_role}</span>}
        <span className="spacer" />
        <input placeholder="Search constructs…" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 210 }} />
        {canEdit && (
          <>
            <button onClick={() => setNewOpen(true)}>+ New</button>
            <button className="primary" onClick={() => setImportOpen(true)}>
              Import
            </button>
          </>
        )}
      </div>
      <div
        className="content"
        onDragOver={(e) => {
          if (!canEdit) return
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          if (!canEdit) return
          e.preventDefault()
          setDragOver(false)
          if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files)
        }}
        style={dragOver ? { outline: '2px dashed var(--accent)', outlineOffset: -8 } : undefined}
      >
        {project.data?.description && <p className="muted small">{project.data.description}</p>}

        <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) 280px' }}>
          <div className="card">
            <header>
              Constructs
              <span className="spacer" />
              <span className="dim tiny">{sequences.data?.total ?? 0} total</span>
            </header>
            <div className="body">
              {sequences.isLoading && <Spinner />}
              {sequences.data?.items.length === 0 && (
                <Empty>
                  No constructs yet.
                  {canEdit && ' Drag a GenBank / FASTA / SnapGene file here, or use Import.'}
                </Empty>
              )}
              {(sequences.data?.items.length ?? 0) > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th className="num">Length</th>
                      <th>Topology</th>
                      <th className="num">GC%</th>
                      <th className="num">Feat.</th>
                      <th className="num">Ver.</th>
                      <th>Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sequences.data?.items.map((s) => (
                      <tr key={s.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/sequences/${s.id}`)}>
                        <td>
                          <b>{s.name}</b>
                          {s.description && <div className="tiny dim truncate" style={{ maxWidth: 380 }}>{s.description}</div>}
                        </td>
                        <td className="num">{formatNumber(s.length)}</td>
                        <td>
                          <span className="tag">{s.topology}</span>
                        </td>
                        <td className="num">{s.gc_content}</td>
                        <td className="num">{s.feature_count}</td>
                        <td className="num">{s.current_version}</td>
                        <td className="tiny dim">{s.source_format}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <div className="col">
            <div className="card">
              <header>
                Members
                <span className="spacer" />
                {project.data?.my_role === 'owner' && (
                  <button className="sm" onClick={() => setMemberOpen(true)}>
                    + add
                  </button>
                )}
              </header>
              <div className="body">
                <div className="split-list">
                  {project.data?.members?.map((m) => (
                    <div className="list-item" key={m.id} style={{ cursor: 'default' }}>
                      <div className="grow">
                        <div className="title">{m.username}</div>
                        <div className="tiny dim">{m.email}</div>
                      </div>
                      <span className="tag">{m.role}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="card">
              <header>Import formats</header>
              <div className="body tiny muted">
                <p style={{ marginTop: 0 }}>
                  GenBank (.gb/.gbk), FASTA (.fa/.fasta), EMBL, FASTQ and SnapGene (.dna) — features, topology and
                  qualifiers are preserved where the format carries them.
                </p>
                <p style={{ marginBottom: 0 }}>
                  Exports: GenBank (round-trips into SnapGene/Benchling), FASTA and raw text.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {importOpen && (
        <Modal
          title="Import sequences"
          onClose={() => setImportOpen(false)}
          footer={
            <>
              <label className="inline" style={{ marginRight: 'auto' }}>
                <input type="checkbox" checked={autoAnnotate} onChange={(e) => setAutoAnnotate(e.target.checked)} /> auto-annotate on import
              </label>
              <button onClick={() => setImportOpen(false)}>Cancel</button>
              <button
                className="primary"
                onClick={() => importText.mutate()}
                disabled={(!pasteText && !pasteUrl) || importText.isPending}
              >
                Import text / URL
              </button>
            </>
          }
        >
          <div className="col">
            <div
              className={`dropzone${dragOver ? ' over' : ''}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setDragOver(false)
                if (e.dataTransfer.files.length) void uploadFiles(e.dataTransfer.files)
              }}
            >
              <div style={{ fontSize: 22 }}>⤓</div>
              Drop files here or click to choose
              <div className="tiny dim">.gb .gbk .fasta .fa .embl .fastq .dna .txt — multiple files allowed</div>
              <input
                ref={fileRef}
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => e.target.files && uploadFiles(e.target.files)}
              />
            </div>
            <label className="field">
              Paste sequence or file content
              <textarea value={pasteText} onChange={(e) => setPasteText(e.target.value)} placeholder=">my_construct&#10;ATGC…" />
            </label>
            <label className="field">
              …or fetch from an allow-listed URL
              <input value={pasteUrl} onChange={(e) => setPasteUrl(e.target.value)} placeholder="https://eutils.ncbi.nlm.nih.gov/…" />
            </label>
          </div>
        </Modal>
      )}

      {newOpen && (
        <Modal
          title="New construct"
          onClose={() => setNewOpen(false)}
          footer={
            <>
              <button onClick={() => setNewOpen(false)}>Cancel</button>
              <button className="primary" onClick={() => createSequence.mutate()} disabled={!draft.name || createSequence.isPending}>
                Create
              </button>
            </>
          }
        >
          <div className="col">
            <label className="field">
              Name
              <input autoFocus value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </label>
            <label className="field">
              Topology
              <select value={draft.topology} onChange={(e) => setDraft({ ...draft, topology: e.target.value as 'linear' | 'circular' })}>
                <option value="linear">linear</option>
                <option value="circular">circular (plasmid)</option>
              </select>
            </label>
            <label className="field">
              Sequence
              <textarea value={draft.sequence} onChange={(e) => setDraft({ ...draft, sequence: e.target.value })} placeholder="ATGC…" />
            </label>
            <div className="tiny dim">{formatBp(draft.sequence.replace(/[^A-Za-z]/g, '').length)} entered</div>
          </div>
        </Modal>
      )}

      {memberOpen && (
        <Modal
          title="Add member"
          onClose={() => setMemberOpen(false)}
          footer={
            <>
              <button onClick={() => setMemberOpen(false)}>Cancel</button>
              <button className="primary" onClick={() => addMember.mutate()} disabled={!member.username || addMember.isPending}>
                Add
              </button>
            </>
          }
        >
          <div className="col">
            <label className="field">
              Username or email
              <input value={member.username} onChange={(e) => setMember({ ...member, username: e.target.value })} />
            </label>
            <label className="field">
              Role
              <select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}>
                <option value="viewer">viewer — read only</option>
                <option value="editor">editor — edit sequences</option>
                <option value="owner">owner — manage project</option>
              </select>
            </label>
          </div>
        </Modal>
      )}
    </>
  )
}

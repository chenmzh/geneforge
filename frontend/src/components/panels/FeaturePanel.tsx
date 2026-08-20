/** Feature list + inline editor (add / edit / delete / auto-annotate). */
import { useState } from 'react'
import { api } from '@/api/client'
import type { Feature, SequenceDetail } from '@/api/types'
import { featureColor, formatNumber } from '@/lib/seq'
import { reportError, useUi } from '@/store/auth'
import type { Selection } from '../SequenceViewer'
import { Empty, Modal } from '../Ui'

const TYPES = [
  'CDS', 'gene', 'promoter', 'terminator', 'RBS', 'rep_origin', 'primer_bind',
  'protein_bind', 'regulatory', 'polyA_signal', 'LTR', 'misc_feature', 'sig_peptide',
]

interface Props {
  sequence: SequenceDetail
  selection: Selection | null
  selectedFeatureId: string | null
  canEdit: boolean
  onSelectFeature: (feature: Feature | null) => void
  onChanged: () => void
}

export default function FeaturePanel({ sequence, selection, selectedFeatureId, canEdit, onSelectFeature, onChanged }: Props) {
  const notify = useUi((s) => s.notify)
  const [editing, setEditing] = useState<Feature | null>(null)
  const [creating, setCreating] = useState(false)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')

  const selStart = selection ? Math.min(selection.start, selection.end) : 0
  const selEnd = selection ? Math.max(selection.start, selection.end) : 0

  const [draft, setDraft] = useState({ name: '', type: 'misc_feature', strand: 1, color: '', start: 0, end: 0 })

  const openCreate = () => {
    setDraft({
      name: '',
      type: 'misc_feature',
      strand: 1,
      color: '',
      start: selStart,
      end: selEnd > selStart ? selEnd : Math.min(sequence.length, selStart + 30),
    })
    setCreating(true)
  }

  const submitCreate = async () => {
    setBusy(true)
    try {
      await api.addFeature(sequence.id, {
        name: draft.name || draft.type,
        type: draft.type,
        strand: draft.strand,
        color: draft.color || null,
        start: draft.start,
        end: draft.end,
        segments: [[draft.start, draft.end]],
        qualifiers: { label: draft.name || draft.type },
      })
      notify('Feature added', 'success')
      setCreating(false)
      onChanged()
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const submitEdit = async () => {
    if (!editing) return
    setBusy(true)
    try {
      await api.updateFeature(sequence.id, editing.id, {
        name: editing.name,
        type: editing.type,
        strand: editing.strand,
        color: editing.color,
        start: editing.start,
        end: editing.end,
      })
      notify('Feature updated', 'success')
      setEditing(null)
      onChanged()
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const remove = async (feature: Feature) => {
    if (!confirm(`Delete feature "${feature.name}"?`)) return
    try {
      await api.deleteFeature(sequence.id, feature.id)
      notify('Feature deleted', 'success')
      if (selectedFeatureId === feature.id) onSelectFeature(null)
      onChanged()
    } catch (e) {
      reportError(e)
    }
  }

  const autoAnnotate = async (replace: boolean) => {
    setBusy(true)
    try {
      const updated = await api.autoAnnotate(sequence.id, replace)
      notify(`Auto-annotation done — ${updated.features.length} features`, 'success')
      onChanged()
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const rows = sequence.features.filter(
    (f) => !filter || f.name.toLowerCase().includes(filter.toLowerCase()) || f.type.toLowerCase().includes(filter.toLowerCase()),
  )

  return (
    <div className="col">
      <div className="row">
        <input placeholder="Filter features…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ flex: 1 }} />
        {canEdit && (
          <>
            <button className="sm" onClick={openCreate} disabled={busy}>
              + Add
            </button>
            <button className="sm" onClick={() => autoAnnotate(false)} disabled={busy} title="Detect known elements and ORFs, keeping existing features">
              Auto-annotate
            </button>
          </>
        )}
      </div>
      {canEdit && (
        <div className="row tiny dim">
          <button className="ghost sm" onClick={() => autoAnnotate(true)} disabled={busy}>
            Replace all with detected features
          </button>
        </div>
      )}

      {rows.length === 0 ? (
        <Empty>No features. Select a region and click “Add”, or run auto-annotate.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: '42%' }}>Name</th>
              <th style={{ width: '20%' }}>Type</th>
              <th className="num" style={{ width: '26%' }}>Range</th>
              <th style={{ width: '12%' }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr
                key={f.id}
                className={selectedFeatureId === f.id ? 'selected' : ''}
                onClick={() => onSelectFeature(f)}
                style={{ cursor: 'pointer' }}
              >
                <td>
                  <span
                    style={{
                      display: 'inline-block', width: 8, height: 8, borderRadius: 2, marginRight: 6,
                      background: featureColor(f.type, f.color),
                    }}
                  />
                  {f.name} {f.strand === -1 ? '◄' : f.strand === 1 ? '►' : ''}
                </td>
                <td className="dim tiny">{f.type}</td>
                <td className="num tiny" title={`${f.end - f.start} bp`}>
                  {formatNumber(f.start + 1)}–{formatNumber(f.end)}
                </td>
                <td className="right nowrap">
                  {canEdit && (
                    <>
                      <button className="ghost sm" onClick={(e) => { e.stopPropagation(); setEditing({ ...f }) }} title="Edit">
                        ✎
                      </button>
                      <button className="ghost sm" onClick={(e) => { e.stopPropagation(); remove(f) }} title="Delete">
                        ✕
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {creating && (
        <Modal
          title="Add feature"
          onClose={() => setCreating(false)}
          footer={
            <>
              <button onClick={() => setCreating(false)}>Cancel</button>
              <button className="primary" onClick={submitCreate} disabled={busy || draft.end <= draft.start}>
                Add feature
              </button>
            </>
          }
        >
          <div className="grid cols-2">
            <label className="field">
              Name
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="e.g. EGFP" />
            </label>
            <label className="field">
              Type
              <select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
                {TYPES.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Start (1-based)
              <input type="number" value={draft.start + 1} onChange={(e) => setDraft({ ...draft, start: Math.max(0, Number(e.target.value) - 1) })} />
            </label>
            <label className="field">
              End
              <input type="number" value={draft.end} onChange={(e) => setDraft({ ...draft, end: Number(e.target.value) })} />
            </label>
            <label className="field">
              Strand
              <select value={draft.strand} onChange={(e) => setDraft({ ...draft, strand: Number(e.target.value) })}>
                <option value={1}>forward (+)</option>
                <option value={-1}>reverse (−)</option>
                <option value={0}>none</option>
              </select>
            </label>
            <label className="field">
              Colour
              <input value={draft.color} onChange={(e) => setDraft({ ...draft, color: e.target.value })} placeholder="#4f8ef7 (optional)" />
            </label>
          </div>
        </Modal>
      )}

      {editing && (
        <Modal
          title={`Edit “${editing.name}”`}
          onClose={() => setEditing(null)}
          footer={
            <>
              <button onClick={() => setEditing(null)}>Cancel</button>
              <button className="primary" onClick={submitEdit} disabled={busy}>
                Save
              </button>
            </>
          }
        >
          <div className="grid cols-2">
            <label className="field">
              Name
              <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            </label>
            <label className="field">
              Type
              <select value={editing.type} onChange={(e) => setEditing({ ...editing, type: e.target.value })}>
                {[...new Set([editing.type, ...TYPES])].map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Start (1-based)
              <input type="number" value={editing.start + 1} onChange={(e) => setEditing({ ...editing, start: Math.max(0, Number(e.target.value) - 1) })} />
            </label>
            <label className="field">
              End
              <input type="number" value={editing.end} onChange={(e) => setEditing({ ...editing, end: Number(e.target.value) })} />
            </label>
            <label className="field">
              Strand
              <select value={editing.strand} onChange={(e) => setEditing({ ...editing, strand: Number(e.target.value) })}>
                <option value={1}>forward (+)</option>
                <option value={-1}>reverse (−)</option>
                <option value={0}>none</option>
              </select>
            </label>
            <label className="field">
              Colour
              <input value={editing.color ?? ''} onChange={(e) => setEditing({ ...editing, color: e.target.value })} />
            </label>
          </div>
          {Object.keys(editing.qualifiers ?? {}).length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary className="small muted">GenBank qualifiers</summary>
              <pre className="tiny mono" style={{ whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(editing.qualifiers, null, 2)}
              </pre>
            </details>
          )}
        </Modal>
      )}
    </div>
  )
}

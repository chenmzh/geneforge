/**
 * Sequence workbench — the main editing surface: linear viewer, circular map,
 * edit operations, enzyme overlay, search and the analysis side panels.
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '@/api/client'
import type { EditOp, EnzymeScanResult, Feature } from '@/api/types'
import PlasmidMap from '@/components/PlasmidMap'
import SequenceViewer, { type Selection } from '@/components/SequenceViewer'
import AlignPanel from '@/components/panels/AlignPanel'
import { AnalysisPanel, VersionPanel } from '@/components/panels/AnalysisPanel'
import EnzymePanel from '@/components/panels/EnzymePanel'
import FeaturePanel from '@/components/panels/FeaturePanel'
import PrimerPanel from '@/components/panels/PrimerPanel'
import { Modal, Spinner } from '@/components/Ui'
import { copyToClipboard, downloadText, findMatches, formatNumber, gcContent, quickTm, reverseComplement } from '@/lib/seq'
import { reportError, useUi } from '@/store/auth'

type ViewMode = 'linear' | 'circular' | 'split'
type Tab = 'features' | 'enzymes' | 'primers' | 'align' | 'analysis' | 'versions'

export default function SequenceWorkbench() {
  const { sequenceId = '' } = useParams()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const notify = useUi((s) => s.notify)

  const [view, setView] = useState<ViewMode>('split')
  const [tab, setTab] = useState<Tab>('features')
  const [selection, setSelection] = useState<Selection | null>(null)
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null)
  const [showComplement, setShowComplement] = useState(true)
  const [showTranslation, setShowTranslation] = useState(false)
  const [showEnzymes, setShowEnzymes] = useState(true)
  const [search, setSearch] = useState('')
  const [activeEnzymes, setActiveEnzymes] = useState<string[]>([])
  const [scan, setScan] = useState<EnzymeScanResult | null>(null)
  const [scanning, setScanning] = useState(false)
  const [insertOpen, setInsertOpen] = useState(false)
  const [insertPayload, setInsertPayload] = useState('')
  const [busy, setBusy] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const [newName, setNewName] = useState('')

  const seqQuery = useQuery({ queryKey: ['sequence', sequenceId], queryFn: () => api.sequence(sequenceId) })
  const project = useQuery({
    queryKey: ['project', seqQuery.data?.project_id],
    queryFn: () => api.project(seqQuery.data!.project_id),
    enabled: !!seqQuery.data?.project_id,
  })
  const stats = useQuery({
    queryKey: ['stats', sequenceId, seqQuery.data?.current_version],
    queryFn: () => api.stats(sequenceId),
    enabled: !!seqQuery.data,
  })

  const sequence = seqQuery.data
  const canEdit = project.data?.my_role === 'owner' || project.data?.my_role === 'editor'

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ['sequence', sequenceId] })
    void qc.invalidateQueries({ queryKey: ['stats', sequenceId] })
    void qc.invalidateQueries({ queryKey: ['sequences'] })
  }

  const rescan = async (commonOnly: boolean, uniqueOnly: boolean) => {
    if (!sequence) return
    setScanning(true)
    try {
      setScan(await api.enzymeSearch({ sequence_id: sequence.id, common_only: commonOnly, unique_only: uniqueOnly }))
    } catch (e) {
      reportError(e)
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => {
    setSelection(null)
    setSelectedFeatureId(null)
    setScan(null)
  }, [sequenceId])

  // Scan the common enzyme set as soon as a construct opens so unique cut sites
  // are visible in both views without having to open the Enzymes tab first.
  useEffect(() => {
    if (!sequence) return
    let cancelled = false
    setScanning(true)
    api
      .enzymeSearch({ sequence_id: sequence.id, common_only: true })
      .then((res) => {
        if (!cancelled) setScan(res)
      })
      .catch(reportError)
      .finally(() => {
        if (!cancelled) setScanning(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence?.id, sequence?.current_version])

  const hits = useMemo(() => (sequence && search.length > 1 ? findMatches(sequence.sequence, search) : []), [sequence, search])

  const visibleSites = useMemo(() => {
    if (!scan) return []
    if (activeEnzymes.length > 0) return scan.sites.filter((s) => activeEnzymes.includes(s.enzyme))
    return scan.summary.filter((r) => r.unique).flatMap((r) => scan.sites.filter((s) => s.enzyme === r.enzyme))
  }, [scan, activeEnzymes])

  const selStart = selection ? Math.min(selection.start, selection.end) : 0
  const selEnd = selection ? Math.max(selection.start, selection.end) : 0
  const selLength = selEnd - selStart
  const selSeq = sequence ? sequence.sequence.slice(selStart, selEnd) : ''

  const applyEdit = async (ops: EditOp[], message: string) => {
    if (!sequence) return
    setBusy(true)
    try {
      await api.editSequence(sequence.id, ops, message)
      notify(message, 'success')
      setSelection(null)
      refresh()
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const doExport = async (format: 'genbank' | 'fasta' | 'plain') => {
    if (!sequence) return
    try {
      const text = await api.exportSequence(sequence.id, format)
      const ext = format === 'genbank' ? 'gb' : format === 'fasta' ? 'fasta' : 'txt'
      downloadText(`${sequence.name}.${ext}`, text)
      notify(`Exported ${format}`, 'success')
    } catch (e) {
      reportError(e)
    }
  }

  if (seqQuery.isLoading || !sequence) {
    return (
      <div className="content">
        <Spinner label="Loading construct…" />
      </div>
    )
  }

  const selectFeature = (feature: Feature | null) => {
    setSelectedFeatureId(feature?.id ?? null)
    if (feature) setSelection({ start: feature.start, end: feature.end })
  }

  return (
    <>
      <div className="topbar">
        <Link to={`/projects/${sequence.project_id}`} className="dim nowrap">
          ← {project.data?.name ?? 'Project'}
        </Link>
        <h1
          onDoubleClick={() => {
            if (!canEdit) return
            setNewName(sequence.name)
            setRenaming(true)
          }}
          title={canEdit ? 'Double-click to rename' : undefined}
        >
          {sequence.name}
        </h1>
        <span className="tag">{formatNumber(sequence.length)} bp</span>
        <span className="tag">{sequence.topology}</span>
        <span className="tag">v{sequence.current_version}</span>
        {sequence.gc_content > 0 && <span className="tag">GC {sequence.gc_content}%</span>}
        <span className="spacer" />
        {canEdit && (
          <button
            className="sm"
            disabled={busy}
            onClick={() =>
              applyEdit(
                [{ op: 'set_topology', topology: sequence.topology === 'circular' ? 'linear' : 'circular' }],
                `Set topology to ${sequence.topology === 'circular' ? 'linear' : 'circular'}`,
              )
            }
          >
            make {sequence.topology === 'circular' ? 'linear' : 'circular'}
          </button>
        )}
        <button className="sm" onClick={() => doExport('genbank')}>
          ⭳ GenBank
        </button>
        <button className="sm" onClick={() => doExport('fasta')}>
          ⭳ FASTA
        </button>
        {canEdit && (
          <button
            className="sm danger"
            onClick={async () => {
              if (!confirm(`Delete construct “${sequence.name}”? This cannot be undone.`)) return
              await api.deleteSequence(sequence.id).catch(reportError)
              notify('Construct deleted', 'success')
              navigate(`/projects/${sequence.project_id}`)
            }}
          >
            delete
          </button>
        )}
      </div>

      <div className="workbench">
        <div className="viewer-pane">
          <div className="seq-toolbar">
            <div className="tabs" style={{ border: 'none' }}>
              {(['linear', 'circular', 'split'] as ViewMode[]).map((m) => (
                <button key={m} className={view === m ? 'active' : ''} onClick={() => setView(m)}>
                  {m}
                </button>
              ))}
            </div>
            <span style={{ width: 8 }} />
            <input
              placeholder="Find motif (IUPAC ok)…"
              value={search}
              onChange={(e) => setSearch(e.target.value.toUpperCase().replace(/[^ACGTURYSWKMBDHVN]/g, ''))}
              style={{ width: 190 }}
            />
            {hits.length > 0 && (
              <span className="tag info nowrap">
                {hits.length} hit{hits.length === 1 ? '' : 's'}
                <button
                  className="ghost sm"
                  onClick={() => setSelection({ start: hits[0].start, end: hits[0].end })}
                  title="Select first hit"
                >
                  ⤓
                </button>
              </span>
            )}
            <span className="spacer" style={{ flex: 1 }} />
            <label className="inline">
              <input type="checkbox" checked={showComplement} onChange={(e) => setShowComplement(e.target.checked)} /> complement
            </label>
            <label className="inline">
              <input type="checkbox" checked={showTranslation} onChange={(e) => setShowTranslation(e.target.checked)} /> frames
            </label>
            <label className="inline">
              <input type="checkbox" checked={showEnzymes} onChange={(e) => setShowEnzymes(e.target.checked)} /> sites
            </label>
          </div>

          {canEdit && (
            <div className="seq-toolbar" style={{ paddingTop: 4, paddingBottom: 4 }}>
              <span className="tiny dim">Edit:</span>
              <button className="sm" disabled={!selection || busy} onClick={() => setInsertOpen(true)}>
                insert / replace
              </button>
              <button
                className="sm"
                disabled={selLength < 1 || busy}
                onClick={() => applyEdit([{ op: 'delete', start: selStart, end: selEnd }], `Delete ${selLength} bp`)}
              >
                delete selection
              </button>
              <button
                className="sm"
                disabled={selLength < 2 || busy}
                onClick={() =>
                  applyEdit([{ op: 'reverse_complement_range', start: selStart, end: selEnd }], `Reverse complement ${selLength} bp`)
                }
              >
                rev-comp selection
              </button>
              <button
                className="sm"
                disabled={busy}
                onClick={() => applyEdit([{ op: 'reverse_complement' }], 'Reverse complement whole sequence')}
              >
                rev-comp all
              </button>
              {sequence.topology === 'circular' && (
                <button
                  className="sm"
                  disabled={!selection || busy}
                  onClick={() => applyEdit([{ op: 'set_origin', origin: selStart }], `Set origin to ${selStart + 1}`)}
                >
                  set origin here
                </button>
              )}
            </div>
          )}

          {(view === 'linear' || view === 'split') && (
            <SequenceViewer
              sequence={sequence.sequence}
              features={sequence.features}
              sites={showEnzymes ? visibleSites : []}
              hits={hits}
              selection={selection}
              onSelectionChange={setSelection}
              selectedFeatureId={selectedFeatureId}
              onFeatureClick={selectFeature}
              showComplement={showComplement}
              showTranslation={showTranslation}
              showEnzymes={showEnzymes}
            />
          )}

          {(view === 'circular' || view === 'split') && (
            <div className="map-wrap" style={view === 'split' ? { maxHeight: '48%', borderTop: '1px solid var(--line)' } : undefined}>
              <PlasmidMap
                name={sequence.name}
                length={sequence.length}
                topology={sequence.topology}
                features={sequence.features}
                sites={showEnzymes ? visibleSites : []}
                gcTrack={stats.data?.gc_track ?? []}
                selection={selection}
                selectedFeatureId={selectedFeatureId}
                onFeatureClick={selectFeature}
                onPositionClick={(pos) => setSelection({ start: pos, end: pos })}
                size={view === 'split' ? 440 : 620}
              />
            </div>
          )}

          <div className="selection-bar">
            {selection ? (
              <>
                <span>
                  Selection <b>{formatNumber(selStart + 1)}–{formatNumber(selEnd)}</b>
                </span>
                <span>
                  length <b>{formatNumber(selLength)}</b> bp
                </span>
                <span>
                  GC <b>{gcContent(selSeq)}%</b>
                </span>
                {selLength >= 8 && selLength <= 60 && (
                  <span>
                    Tm ≈ <b>{quickTm(selSeq)} °C</b>
                  </span>
                )}
                <button className="ghost sm" onClick={() => copyToClipboard(selSeq).then((ok) => notify(ok ? 'Sequence copied' : 'Copy failed', ok ? 'success' : 'error'))}>
                  copy
                </button>
                <button className="ghost sm" onClick={() => copyToClipboard(reverseComplement(selSeq)).then(() => notify('Reverse complement copied', 'success'))}>
                  copy rev-comp
                </button>
                <button className="ghost sm" onClick={() => setSelection(null)}>
                  clear
                </button>
              </>
            ) : (
              <span className="dim">Drag across the sequence to select; click a feature to select its span.</span>
            )}
          </div>
        </div>

        <div className="side-pane">
          <div className="tabs">
            {(['features', 'enzymes', 'primers', 'align', 'analysis', 'versions'] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
                {t === 'features' ? `Features (${sequence.features.length})` : t}
              </button>
            ))}
          </div>
          <div className="panel-body">
            {tab === 'features' && (
              <FeaturePanel
                sequence={sequence}
                selection={selection}
                selectedFeatureId={selectedFeatureId}
                canEdit={!!canEdit}
                onSelectFeature={selectFeature}
                onChanged={refresh}
              />
            )}
            {tab === 'enzymes' && (
              <EnzymePanel
                sequence={sequence}
                activeEnzymes={activeEnzymes}
                onActiveEnzymesChange={setActiveEnzymes}
                scan={scan}
                scanning={scanning}
                onRescan={rescan}
              />
            )}
            {tab === 'primers' && (
              <PrimerPanel sequence={sequence} selection={selection} canEdit={!!canEdit} onHighlight={setSelection} />
            )}
            {tab === 'align' && <AlignPanel sequence={sequence} onHighlight={setSelection} />}
            {tab === 'analysis' && <AnalysisPanel sequence={sequence} selection={selection} onHighlight={setSelection} />}
            {tab === 'versions' && <VersionPanel sequence={sequence} canEdit={!!canEdit} onRestored={refresh} />}
          </div>
        </div>
      </div>

      {insertOpen && (
        <Modal
          title={selLength > 0 ? `Replace ${formatNumber(selLength)} bp` : `Insert at ${formatNumber(selStart + 1)}`}
          onClose={() => setInsertOpen(false)}
          footer={
            <>
              <button onClick={() => setInsertOpen(false)}>Cancel</button>
              <button
                className="primary"
                disabled={busy || !insertPayload.replace(/[^A-Za-z]/g, '')}
                onClick={async () => {
                  const payload = insertPayload.replace(/[^A-Za-z]/g, '').toUpperCase()
                  setInsertOpen(false)
                  setInsertPayload('')
                  await applyEdit(
                    selLength > 0
                      ? [{ op: 'replace', start: selStart, end: selEnd, payload }]
                      : [{ op: 'insert', position: selStart, payload }],
                    selLength > 0 ? `Replace ${selLength} bp with ${payload.length} bp` : `Insert ${payload.length} bp at ${selStart + 1}`,
                  )
                }}
              >
                Apply
              </button>
            </>
          }
        >
          <label className="field">
            Sequence to {selLength > 0 ? 'insert in place of the selection' : 'insert'}
            <textarea value={insertPayload} onChange={(e) => setInsertPayload(e.target.value)} placeholder="GAATTC…" />
          </label>
          <p className="tiny dim">
            Features are remapped automatically and the edit is stored as a new version, so you can always roll back
            from the Versions tab.
          </p>
        </Modal>
      )}

      {renaming && (
        <Modal
          title="Rename construct"
          onClose={() => setRenaming(false)}
          footer={
            <>
              <button onClick={() => setRenaming(false)}>Cancel</button>
              <button
                className="primary"
                onClick={async () => {
                  try {
                    await api.updateSequence(sequence.id, { name: newName })
                    setRenaming(false)
                    notify('Renamed', 'success')
                    refresh()
                  } catch (e) {
                    reportError(e)
                  }
                }}
              >
                Save
              </button>
            </>
          }
        >
          <label className="field">
            Name
            <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} />
          </label>
        </Modal>
      )}
    </>
  )
}

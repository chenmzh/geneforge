/** Composition/ORF/translation analysis + version history for one construct. */
import { useEffect, useState } from 'react'
import { api } from '@/api/client'
import type { Orf, SequenceDetail, SequenceStats, SequenceVersion } from '@/api/types'
import { copyToClipboard, formatBp, formatNumber } from '@/lib/seq'
import { reportError, useUi } from '@/store/auth'
import type { Selection } from '../SequenceViewer'
import { Empty, Spinner, Stat } from '../Ui'

export function AnalysisPanel({
  sequence,
  selection,
  onHighlight,
}: {
  sequence: SequenceDetail
  selection: Selection | null
  onHighlight: (region: Selection | null) => void
}) {
  const notify = useUi((s) => s.notify)
  const [stats, setStats] = useState<SequenceStats | null>(null)
  const [orfs, setOrfs] = useState<Orf[] | null>(null)
  const [minAa, setMinAa] = useState(80)
  const [busy, setBusy] = useState(false)
  const [protein, setProtein] = useState<string>('')

  useEffect(() => {
    api.stats(sequence.id).then(setStats).catch(reportError)
  }, [sequence.id, sequence.current_version])

  const findOrfs = async () => {
    setBusy(true)
    try {
      const res = await api.orfs({ sequence_id: sequence.id, min_aa: minAa })
      setOrfs(res.orfs)
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const translateSelection = async () => {
    if (!selection) return
    const start = Math.min(selection.start, selection.end)
    const end = Math.max(selection.start, selection.end)
    if (end - start < 3) return
    try {
      const res = await api.translate({ sequence: sequence.sequence.slice(start, end), frame: 0 })
      setProtein(res.protein ?? '')
    } catch (e) {
      reportError(e)
    }
  }

  return (
    <div className="col">
      {!stats ? (
        <Spinner label="Computing statistics…" />
      ) : (
        <>
          <div className="grid cols-4">
            <Stat label="Length" value={formatBp(stats.length)} />
            <Stat label="GC" value={`${stats.gc}%`} />
            <Stat label="Tm (duplex)" value={`${stats.melting_temp} °C`} />
            <Stat label="ORFs ≥50 aa" value={stats.orf_count} />
          </div>
          <div className="card">
            <div className="body">
              <dl className="kv">
                <dt>A / C / G / T</dt>
                <dd>
                  {formatNumber(stats.a)} / {formatNumber(stats.c)} / {formatNumber(stats.g)} / {formatNumber(stats.t)}
                </dd>
                <dt>Ambiguous</dt>
                <dd>{formatNumber(stats.ambiguous)}</dd>
                <dt>MW (dsDNA)</dt>
                <dd>{(stats.molecular_weight / 1000).toFixed(1)} kDa</dd>
                <dt>Topology</dt>
                <dd>{stats.topology}</dd>
              </dl>
            </div>
          </div>
          {stats.gc_track.length > 2 && <GcTrack track={stats.gc_track} length={stats.length} onSeek={(p) => onHighlight({ start: p, end: p + 1 })} />}
        </>
      )}

      <div className="card">
        <header>
          Open reading frames
          <span className="spacer" />
          <label className="inline">
            min aa
            <input
              type="number"
              value={minAa}
              onChange={(e) => setMinAa(Number(e.target.value))}
              style={{ width: 68 }}
            />
          </label>
          <button className="sm" onClick={findOrfs} disabled={busy}>
            find
          </button>
        </header>
        <div className="body">
          {busy && <Spinner />}
          {orfs && orfs.length === 0 && <Empty>No ORFs above the threshold.</Empty>}
          {orfs && orfs.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th className="num">Start</th>
                  <th className="num">End</th>
                  <th>Strand</th>
                  <th className="num">aa</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {orfs.slice(0, 40).map((o, i) => (
                  <tr key={i}>
                    <td className="num">{formatNumber(o.start + 1)}</td>
                    <td className="num">{formatNumber(o.end)}</td>
                    <td>{o.strand === 1 ? '+' : '−'}</td>
                    <td className="num">{o.aa_length}</td>
                    <td className="right nowrap">
                      <button className="ghost sm" onClick={() => onHighlight({ start: o.start, end: o.end })}>
                        show
                      </button>
                      <button
                        className="ghost sm"
                        onClick={() => copyToClipboard(o.protein).then((ok) => notify(ok ? 'Protein copied' : 'Copy failed', ok ? 'success' : 'error'))}
                      >
                        aa
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <header>
          Translate selection
          <span className="spacer" />
          <button className="sm" onClick={translateSelection} disabled={!selection || Math.abs(selection.end - selection.start) < 3}>
            translate
          </button>
        </header>
        <div className="body">
          {protein ? (
            <div className="mono tiny" style={{ wordBreak: 'break-all' }}>
              {protein}
            </div>
          ) : (
            <p className="tiny dim" style={{ margin: 0 }}>
              Select a region in the viewer, then translate it in frame 1.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

function GcTrack({
  track,
  length,
  onSeek,
}: {
  track: { start: number; end: number; gc: number }[]
  length: number
  onSeek: (pos: number) => void
}) {
  const w = 320
  const h = 54
  const points = track
    .map((band, i) => {
      const x = (band.start / Math.max(1, length)) * w
      const y = h - ((band.gc - 20) / 60) * h
      return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${Math.max(1, Math.min(h - 1, y)).toFixed(1)}`
    })
    .join(' ')
  return (
    <div className="card">
      <header>GC content</header>
      <div className="body">
        <svg
          width="100%"
          height={h}
          viewBox={`0 0 ${w} ${h}`}
          preserveAspectRatio="none"
          style={{ cursor: 'crosshair' }}
          onClick={(e) => {
            const rect = (e.target as SVGElement).closest('svg')!.getBoundingClientRect()
            onSeek(Math.round(((e.clientX - rect.left) / rect.width) * length))
          }}
        >
          <line x1={0} y1={h / 2} x2={w} y2={h / 2} stroke="#263340" strokeDasharray="3 3" />
          <path d={points} fill="none" stroke="#38bdf8" strokeWidth={1.2} />
        </svg>
        <div className="row tiny dim">
          <span>20%</span>
          <span className="spacer" style={{ flex: 1 }} />
          <span>50%</span>
          <span className="spacer" style={{ flex: 1 }} />
          <span>80%</span>
        </div>
      </div>
    </div>
  )
}

export function VersionPanel({
  sequence,
  canEdit,
  onRestored,
}: {
  sequence: SequenceDetail
  canEdit: boolean
  onRestored: () => void
}) {
  const notify = useUi((s) => s.notify)
  const [versions, setVersions] = useState<SequenceVersion[] | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => {
    api.versions(sequence.id).then(setVersions).catch(reportError)
  }

  useEffect(load, [sequence.id, sequence.current_version])

  const restore = async (version: number) => {
    if (!confirm(`Restore version ${version}? The current state is kept as a new version.`)) return
    setBusy(true)
    try {
      await api.restoreVersion(sequence.id, version)
      notify(`Restored version ${version}`, 'success')
      onRestored()
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  if (!versions) return <Spinner label="Loading history…" />
  if (versions.length === 0) return <Empty>No versions recorded.</Empty>

  return (
    <div className="split-list">
      {versions.map((v) => (
        <div className="list-item" key={v.id} style={{ cursor: 'default' }}>
          <div className="grow">
            <div className="title">
              v{v.version}
              {v.version === sequence.current_version && <span className="tag ok" style={{ marginLeft: 6 }}>current</span>}
            </div>
            <div className="tiny dim">{v.message || '—'}</div>
            <div className="tiny dim">
              {new Date(v.created_at).toLocaleString()} · {formatNumber(v.length)} bp
              {typeof v.diff_summary?.delta === 'number' && (v.diff_summary.delta as number) !== 0 && (
                <span> · {(v.diff_summary.delta as number) > 0 ? '+' : ''}{v.diff_summary.delta as number} bp</span>
              )}
            </div>
          </div>
          {canEdit && v.version !== sequence.current_version && (
            <button className="sm" onClick={() => restore(v.version)} disabled={busy}>
              restore
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

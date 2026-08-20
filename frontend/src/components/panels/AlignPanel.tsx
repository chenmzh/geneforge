/** Alignment panel: pairwise against another construct or pasted read, plus MSA. */
import { useEffect, useState } from 'react'
import { api, isJobRef, waitForJob } from '@/api/client'
import type { AlignResult, MsaResult, SequenceDetail, SequenceSummary } from '@/api/types'
import { formatNumber } from '@/lib/seq'
import { reportError } from '@/store/auth'
import type { Selection } from '../SequenceViewer'
import { Spinner } from '../Ui'

interface Props {
  sequence: SequenceDetail
  onHighlight: (region: Selection | null) => void
}

export default function AlignPanel({ sequence, onHighlight }: Props) {
  const [siblings, setSiblings] = useState<SequenceSummary[]>([])
  const [queryId, setQueryId] = useState('')
  const [pasted, setPasted] = useState('')
  const [mode, setMode] = useState<'glocal' | 'global' | 'local'>('glocal')
  const [result, setResult] = useState<AlignResult | null>(null)
  const [msa, setMsa] = useState<MsaResult | null>(null)
  const [msaIds, setMsaIds] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    api
      .sequences(sequence.project_id)
      .then((page) => setSiblings(page.items.filter((s) => s.id !== sequence.id)))
      .catch(reportError)
  }, [sequence.project_id, sequence.id])

  const runPairwise = async () => {
    setBusy(true)
    setResult(null)
    setProgress(0)
    try {
      const payload: Record<string, unknown> = {
        target_sequence_id: sequence.id,
        mode,
        try_reverse_complement: true,
      }
      if (pasted.trim()) payload.query = pasted.replace(/[^A-Za-z]/g, '')
      else if (queryId) payload.query_sequence_id = queryId
      else return
      const res = await api.align(payload)
      if (isJobRef(res)) {
        const job = await waitForJob(res.job_id, (j) => setProgress(j.progress))
        if (job.status !== 'succeeded') throw new Error(job.error || 'Alignment job failed')
        setResult(job.result as unknown as AlignResult)
      } else {
        setResult(res as AlignResult)
      }
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  const runMsa = async () => {
    setBusy(true)
    setMsa(null)
    try {
      const res = await api.msa({ sequence_ids: [sequence.id, ...msaIds] })
      if (isJobRef(res)) {
        const job = await waitForJob(res.job_id, (j) => setProgress(j.progress))
        if (job.status !== 'succeeded') throw new Error(job.error || 'MSA job failed')
        setMsa(job.result as unknown as MsaResult)
      } else {
        setMsa(res as MsaResult)
      }
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="col">
      <div className="card">
        <header>Pairwise alignment</header>
        <div className="body col">
          <label className="field">
            Query — a construct in this project
            <select value={queryId} onChange={(e) => setQueryId(e.target.value)}>
              <option value="">— choose —</option>
              {siblings.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({formatNumber(s.length)} bp)
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            …or paste a read / sequence
            <textarea
              value={pasted}
              onChange={(e) => setPasted(e.target.value)}
              placeholder="Paste a Sanger read or FASTA body"
              style={{ minHeight: 64 }}
            />
          </label>
          <div className="row">
            <label className="field" style={{ width: 150 }}>
              Mode
              <select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
                <option value="glocal">glocal (read in reference)</option>
                <option value="global">global (end to end)</option>
                <option value="local">local (best region)</option>
              </select>
            </label>
            <button className="primary" onClick={runPairwise} disabled={busy || (!queryId && !pasted.trim())}>
              Align
            </button>
          </div>
          {busy && (
            <div className="col">
              <Spinner label="Aligning…" />
              <div className="progress">
                <i style={{ width: `${Math.round(progress * 100)}%` }} />
              </div>
            </div>
          )}

          {result && (
            <div className="col">
              <div className="row small">
                <span className={`tag ${result.identity > 99 ? 'ok' : result.identity > 90 ? 'info' : 'warn'}`}>
                  {result.identity}% identity
                </span>
                <span className="tag">{result.method}</span>
                <span className="tag">{result.strand === -1 ? 'reverse strand' : 'forward strand'}</span>
                <span className="dim tiny">
                  ref {formatNumber(result.target_start + 1)}–{formatNumber(result.target_end)} · gaps {result.gaps} ·
                  score {result.score}
                </span>
                <button className="ghost sm" onClick={() => onHighlight({ start: result.target_start, end: result.target_end })}>
                  show region
                </button>
              </div>

              {result.variants.length > 0 && (
                <div style={{ maxHeight: 170, overflow: 'auto' }}>
                  <table>
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th className="num">Ref pos</th>
                        <th>Ref</th>
                        <th>Query</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {result.variants.slice(0, 200).map((v, i) => (
                        <tr key={i}>
                          <td className="tiny">{v.kind}</td>
                          <td className="num">{formatNumber(v.ref_pos + 1)}</td>
                          <td className="mono tiny">{v.ref || '–'}</td>
                          <td className="mono tiny">{v.query || '–'}</td>
                          <td className="right">
                            <button
                              className="ghost sm"
                              onClick={() => onHighlight({ start: v.ref_pos, end: v.ref_pos + Math.max(1, v.ref.length) })}
                            >
                              go
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {result.aligned_query && <AlignmentText result={result} />}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <header>Multiple alignment</header>
        <div className="body col">
          <label className="field">
            Include constructs (ctrl/⌘-click for several)
            <select
              multiple
              size={Math.min(6, Math.max(3, siblings.length))}
              value={msaIds}
              onChange={(e) => setMsaIds(Array.from(e.target.selectedOptions).map((o) => o.value))}
            >
              {siblings.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <button onClick={runMsa} disabled={busy || msaIds.length === 0}>
            Align {msaIds.length + 1} sequences
          </button>
          {msa && (
            <div className="col">
              <div className="row small dim">
                reference <b>{msa.reference}</b> · width {formatNumber(msa.width)}
              </div>
              <table>
                <thead>
                  <tr>
                    <th>A</th>
                    <th>B</th>
                    <th className="num">Identity</th>
                  </tr>
                </thead>
                <tbody>
                  {msa.identity_matrix.map((row, i) => (
                    <tr key={i}>
                      <td className="tiny">{row.a}</td>
                      <td className="tiny">{row.b}</td>
                      <td className="num">{row.identity}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <MsaPreview msa={msa} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function AlignmentText({ result }: { result: AlignResult }) {
  const width = 60
  const blocks: React.ReactNode[] = []
  const total = Math.min(result.aligned_query.length, 6000)
  for (let i = 0; i < total; i += width) {
    const q = result.aligned_query.slice(i, i + width)
    const m = result.midline.slice(i, i + width)
    const t = result.aligned_target.slice(i, i + width)
    blocks.push(
      <div className="aln-block" key={i}>
        <div>{`query  ${String(i + 1).padStart(6)} ${q}`}</div>
        <div>{`              ${m}`}</div>
        <div>{`ref    ${String(i + 1).padStart(6)} ${t}`}</div>
      </div>,
    )
  }
  return (
    <details>
      <summary className="small muted">Alignment text</summary>
      <div className="aln">{blocks}</div>
      {result.truncated && <p className="tiny dim">Alignment truncated for display.</p>}
    </details>
  )
}

function MsaPreview({ msa }: { msa: MsaResult }) {
  const width = 120
  const start = 0
  return (
    <details>
      <summary className="small muted">Alignment preview (first {width} columns)</summary>
      <div style={{ overflowX: 'auto', paddingTop: 6 }}>
        {msa.rows.map((row) => (
          <div className="msa-row" key={row.name}>
            <span className="name" title={row.name}>
              {row.name}
            </span>
            <span className="seq">
              {row.aligned
                .slice(start, start + width)
                .split('')
                .map((ch, i) => (
                  <span key={i} className={ch === '-' ? 'd' : undefined}>
                    {ch}
                  </span>
                ))}
            </span>
          </div>
        ))}
        <div className="msa-row">
          <span className="name dim">consensus</span>
          <span className="seq dim">{msa.consensus.slice(start, start + width)}</span>
        </div>
      </div>
    </details>
  )
}

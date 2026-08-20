/** Primer design, single-primer QC, PCR simulation and the project primer store. */
import { useEffect, useState } from 'react'
import { api, isJobRef, waitForJob } from '@/api/client'
import type { PcrResult, PrimerPair, PrimerStats, SequenceDetail, StoredPrimer } from '@/api/types'
import { copyToClipboard, formatNumber } from '@/lib/seq'
import { reportError, useUi } from '@/store/auth'
import type { Selection } from '../SequenceViewer'
import { Empty, Spinner } from '../Ui'

interface Props {
  sequence: SequenceDetail
  selection: Selection | null
  canEdit: boolean
  onHighlight: (region: Selection | null) => void
}

type Mode = 'design' | 'analyze' | 'pcr' | 'saved'

export default function PrimerPanel({ sequence, selection, canEdit, onHighlight }: Props) {
  const notify = useUi((s) => s.notify)
  const [mode, setMode] = useState<Mode>('design')

  // design
  const [pairs, setPairs] = useState<PrimerPair[]>([])
  const [designing, setDesigning] = useState(false)
  const [optTm, setOptTm] = useState(60)
  const [maxPairs, setMaxPairs] = useState(5)
  const [fwdSite, setFwdSite] = useState('')
  const [revSite, setRevSite] = useState('')

  // analyze
  const [oligo, setOligo] = useState('')
  const [stats, setStats] = useState<PrimerStats | null>(null)

  // pcr
  const [fwd, setFwd] = useState('')
  const [rev, setRev] = useState('')
  const [pcr, setPcr] = useState<PcrResult | null>(null)
  const [running, setRunning] = useState(false)

  // saved
  const [saved, setSaved] = useState<StoredPrimer[]>([])

  const selStart = selection ? Math.min(selection.start, selection.end) : 0
  const selEnd = selection ? Math.max(selection.start, selection.end) : 0
  const hasRegion = selEnd - selStart >= 40

  const loadSaved = async () => {
    try {
      setSaved(await api.storedPrimers(sequence.project_id, sequence.id))
    } catch (e) {
      reportError(e)
    }
  }

  useEffect(() => {
    if (mode === 'saved') void loadSaved()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, sequence.id])

  const design = async () => {
    setDesigning(true)
    setPairs([])
    try {
      const target = hasRegion ? { start: selStart, end: selEnd } : { start: 0, end: Math.min(sequence.length, 1000) }
      const res = await api.designPrimers({
        sequence_id: sequence.id,
        target_start: target.start,
        target_end: target.end,
        opt_tm: optTm,
        min_tm: optTm - 3,
        max_tm: optTm + 5,
        max_pairs: maxPairs,
        fwd_enzyme_site: fwdSite || undefined,
        rev_enzyme_site: revSite || undefined,
      })
      if (isJobRef(res)) {
        const job = await waitForJob(res.job_id)
        setPairs(((job.result as { pairs?: PrimerPair[] })?.pairs ?? []) as PrimerPair[])
      } else {
        setPairs(res.pairs)
      }
    } catch (e) {
      reportError(e)
    } finally {
      setDesigning(false)
    }
  }

  const analyze = async () => {
    if (oligo.trim().length < 5) return
    try {
      setStats(await api.analyzePrimer(oligo.trim()))
    } catch (e) {
      reportError(e)
    }
  }

  const runPcr = async () => {
    if (!fwd || !rev) return
    setRunning(true)
    try {
      const res = await api.pcr({ sequence_id: sequence.id, forward: fwd.trim(), reverse: rev.trim() })
      setPcr(res)
      if (res.products[0]) onHighlight({ start: res.products[0].start, end: res.products[0].end })
    } catch (e) {
      reportError(e)
    } finally {
      setRunning(false)
    }
  }

  const savePrimer = async (name: string, seq: string, start?: number, end?: number, strand = 1) => {
    try {
      await api.savePrimer(sequence.project_id, {
        name, sequence: seq, sequence_id: sequence.id, binding_start: start, binding_end: end, strand,
      })
      notify(`Primer ${name} saved`, 'success')
      if (mode === 'saved') void loadSaved()
    } catch (e) {
      reportError(e)
    }
  }

  return (
    <div className="col">
      <div className="tabs">
        {(['design', 'analyze', 'pcr', 'saved'] as Mode[]).map((m) => (
          <button key={m} className={mode === m ? 'active' : ''} onClick={() => setMode(m)}>
            {m === 'design' ? 'Design' : m === 'analyze' ? 'Oligo QC' : m === 'pcr' ? 'PCR' : 'Saved'}
          </button>
        ))}
      </div>

      {mode === 'design' && (
        <div className="col">
          <p className="tiny dim">
            {hasRegion
              ? `Target: ${formatNumber(selStart + 1)}–${formatNumber(selEnd)} (${formatNumber(selEnd - selStart)} bp selected)`
              : 'Select ≥ 40 bp in the viewer to set the amplicon target (defaults to the first 1 kb).'}
          </p>
          <div className="row">
            <label className="field" style={{ width: 96 }}>
              Target Tm
              <input type="number" value={optTm} onChange={(e) => setOptTm(Number(e.target.value))} />
            </label>
            <label className="field" style={{ width: 78 }}>
              Pairs
              <input type="number" min={1} max={10} value={maxPairs} onChange={(e) => setMaxPairs(Number(e.target.value))} />
            </label>
            <label className="field" style={{ flex: 1 }}>
              Fwd 5′ tail (e.g. GGATCC)
              <input value={fwdSite} onChange={(e) => setFwdSite(e.target.value.toUpperCase())} placeholder="optional" />
            </label>
            <label className="field" style={{ flex: 1 }}>
              Rev 5′ tail
              <input value={revSite} onChange={(e) => setRevSite(e.target.value.toUpperCase())} placeholder="optional" />
            </label>
          </div>
          <button className="primary" onClick={design} disabled={designing}>
            {designing ? 'Designing…' : 'Design primer pairs'}
          </button>

          {pairs.length === 0 && !designing && <Empty>No pairs yet.</Empty>}

          {pairs.map((p, i) => (
            <div className="card" key={i}>
              <header>
                <span>
                  Pair {i + 1} · {formatNumber(p.product_size)} bp product
                </span>
                <span className="spacer" />
                <span className={`tag ${p.covers_target ? 'ok' : 'warn'}`}>Ta {p.annealing_temp} °C</span>
              </header>
              <div className="body col">
                {(['forward', 'reverse'] as const).map((side) => {
                  const primer = p[side]
                  const full = side === 'forward' ? p.forward_full : p.reverse_full
                  return (
                    <div key={side} className="col" style={{ gap: 3 }}>
                      <div className="row tiny">
                        <b>{primer.name}</b>
                        <span className="dim">{side === 'forward' ? '→' : '←'}</span>
                        <span className="mono">{full?.sequence ?? primer.sequence}</span>
                      </div>
                      <div className="row tiny dim">
                        <span>Tm {primer.tm} °C</span>
                        <span>GC {primer.gc}%</span>
                        <span>{primer.length} nt</span>
                        <span>hairpin {primer.hairpin_score}</span>
                        <span>dimer {primer.self_dimer_score}</span>
                        <span className="spacer" style={{ flex: 1 }} />
                        <button
                          className="ghost sm"
                          onClick={() => copyToClipboard(full?.sequence ?? primer.sequence).then((ok) => notify(ok ? 'Copied' : 'Copy failed', ok ? 'success' : 'error'))}
                        >
                          copy
                        </button>
                        {canEdit && (
                          <button
                            className="ghost sm"
                            onClick={() => savePrimer(`${sequence.name}_${primer.name}`, full?.sequence ?? primer.sequence, primer.start, primer.end, primer.strand)}
                          >
                            save
                          </button>
                        )}
                        <button className="ghost sm" onClick={() => onHighlight({ start: primer.start, end: primer.end })}>
                          show
                        </button>
                      </div>
                      {primer.warnings.length > 0 && (
                        <div className="tiny" style={{ color: 'var(--warn)' }}>
                          ⚠ {primer.warnings.join('; ')}
                        </div>
                      )}
                    </div>
                  )
                })}
                <div className="row tiny dim">
                  <button
                    className="ghost sm"
                    onClick={() => {
                      setFwd(p.forward_full?.sequence ?? p.forward.sequence)
                      setRev(p.reverse_full?.sequence ?? p.reverse.sequence)
                      setMode('pcr')
                    }}
                  >
                    → simulate PCR with this pair
                  </button>
                  <span>ΔTm {p.tm_difference} °C · pair-dimer {p.pair_dimer_score}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {mode === 'analyze' && (
        <div className="col">
          <label className="field">
            Oligo sequence
            <textarea value={oligo} onChange={(e) => setOligo(e.target.value.toUpperCase().replace(/[^ACGTURYSWKMBDHVN]/g, ''))} placeholder="ACGT…" style={{ minHeight: 60 }} />
          </label>
          <div className="row">
            <button className="primary" onClick={analyze} disabled={oligo.trim().length < 5}>
              Analyse
            </button>
            {selection && selEnd > selStart && (
              <button onClick={() => setOligo(sequence.sequence.slice(selStart, selEnd))}>use selection</button>
            )}
          </div>
          {stats && (
            <div className="card">
              <div className="body">
                <dl className="kv">
                  <dt>Length</dt><dd>{stats.length} nt</dd>
                  <dt>Tm</dt><dd>{stats.tm} °C</dd>
                  <dt>GC</dt><dd>{stats.gc}%</dd>
                  <dt>ΔG (37 °C)</dt><dd>{stats.dg} kcal/mol</dd>
                  <dt>3′ stability</dt><dd>{stats.end_stability} kcal/mol</dd>
                  <dt>GC clamp</dt><dd>{stats.gc_clamp ? 'yes' : 'no'}</dd>
                  <dt>Hairpin</dt><dd>{stats.hairpin_score}</dd>
                  <dt>Self-dimer</dt><dd>{stats.self_dimer_score}</dd>
                  <dt>Max run</dt><dd>{stats.max_homopolymer}</dd>
                </dl>
                {stats.warnings.length > 0 && (
                  <ul className="tiny" style={{ color: 'var(--warn)', marginBottom: 0 }}>
                    {stats.warnings.map((w) => (
                      <li key={w}>{w}</li>
                    ))}
                  </ul>
                )}
                {canEdit && (
                  <button className="sm" style={{ marginTop: 10 }} onClick={() => savePrimer(`oligo_${stats.length}nt`, stats.sequence)}>
                    Save to project
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {mode === 'pcr' && (
        <div className="col">
          <label className="field">
            Forward primer
            <input className="mono" value={fwd} onChange={(e) => setFwd(e.target.value.toUpperCase())} />
          </label>
          <label className="field">
            Reverse primer
            <input className="mono" value={rev} onChange={(e) => setRev(e.target.value.toUpperCase())} />
          </label>
          <button className="primary" onClick={runPcr} disabled={!fwd || !rev || running}>
            {running ? 'Simulating…' : `Simulate on ${sequence.name}`}
          </button>
          {running && <Spinner />}
          {pcr && (
            <div className="col">
              <div className="row small">
                <span className={`tag ${pcr.specific ? 'ok' : 'warn'}`}>
                  {pcr.products.length} product{pcr.products.length === 1 ? '' : 's'}
                </span>
                {pcr.annealing_temp && <span className="tag info">Ta {pcr.annealing_temp} °C</span>}
                <span className="dim tiny">
                  binding sites: {pcr.forward_site_count} fwd / {pcr.reverse_site_count} rev
                </span>
              </div>
              {pcr.warnings.map((w) => (
                <div key={w} className="tiny" style={{ color: 'var(--warn)' }}>
                  ⚠ {w}
                </div>
              ))}
              {pcr.products.length > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th className="num">Size</th>
                      <th className="num">Start</th>
                      <th className="num">End</th>
                      <th className="num">GC%</th>
                      <th>Mismatch</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {pcr.products.map((p, i) => (
                      <tr key={i}>
                        <td className="num">{formatNumber(p.size)}</td>
                        <td className="num">{formatNumber(p.start + 1)}</td>
                        <td className="num">{formatNumber(p.end)}</td>
                        <td className="num">{p.gc}</td>
                        <td className="tiny">
                          {p.forward_mismatches}/{p.reverse_mismatches}
                          {p.crosses_origin && <span className="tag warn" style={{ marginLeft: 4 }}>origin</span>}
                        </td>
                        <td className="right">
                          <button className="ghost sm" onClick={() => onHighlight({ start: p.start, end: p.end })}>
                            show
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      )}

      {mode === 'saved' && (
        <div className="col">
          {saved.length === 0 ? (
            <Empty>No primers stored for this construct yet.</Empty>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Sequence</th>
                  <th className="num">Tm</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {saved.map((p) => (
                  <tr key={p.id}>
                    <td>{p.name}</td>
                    <td className="mono tiny">{p.sequence}</td>
                    <td className="num">{p.tm ?? '—'}</td>
                    <td className="right nowrap">
                      {p.binding_start != null && (
                        <button className="ghost sm" onClick={() => onHighlight({ start: p.binding_start!, end: p.binding_end ?? p.binding_start! })}>
                          show
                        </button>
                      )}
                      {canEdit && (
                        <button
                          className="ghost sm"
                          onClick={async () => {
                            await api.deletePrimer(p.id).catch(reportError)
                            void loadSaved()
                          }}
                        >
                          🗑
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

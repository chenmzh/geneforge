/** Standalone tool bench: run analyses on pasted sequences without saving them. */
import { useState } from 'react'
import { api } from '@/api/client'
import type { DigestResult, EnzymeScanResult, Orf, PrimerStats } from '@/api/types'
import GelView from '@/components/GelView'
import { Empty, Spinner } from '@/components/Ui'
import { formatNumber, gcContent, reverseComplement, translate } from '@/lib/seq'
import { reportError } from '@/store/auth'

type Tool = 'scan' | 'digest' | 'orf' | 'oligo' | 'translate'

export default function ToolBench() {
  const [tool, setTool] = useState<Tool>('scan')
  const [seq, setSeq] = useState('')
  const [circular, setCircular] = useState(false)
  const [enzymes, setEnzymes] = useState('EcoRI, BamHI, HindIII')
  const [busy, setBusy] = useState(false)
  const [scan, setScan] = useState<EnzymeScanResult | null>(null)
  const [digest, setDigest] = useState<DigestResult | null>(null)
  const [orfs, setOrfs] = useState<Orf[] | null>(null)
  const [oligo, setOligo] = useState<PrimerStats | null>(null)

  const clean = seq.replace(/^>.*$/gm, '').replace(/[^A-Za-z]/g, '').toUpperCase()

  const run = async () => {
    if (!clean) return
    setBusy(true)
    try {
      if (tool === 'scan') setScan(await api.enzymeSearch({ sequence: clean, circular, common_only: true }))
      if (tool === 'digest')
        setDigest(
          await api.digest({
            sequence: clean,
            circular,
            enzymes: enzymes.split(/[,\s]+/).filter(Boolean),
          }),
        )
      if (tool === 'orf') setOrfs((await api.orfs({ sequence: clean, min_aa: 50 })).orfs)
      if (tool === 'oligo') setOligo(await api.analyzePrimer(clean.slice(0, 200)))
    } catch (e) {
      reportError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="topbar">
        <h1>Tool bench</h1>
        <span className="dim small">Scratch pad — nothing is stored</span>
        <span className="spacer" />
        <label className="inline">
          <input type="checkbox" checked={circular} onChange={(e) => setCircular(e.target.checked)} /> circular
        </label>
      </div>
      <div className="content">
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
          <div className="card">
            <header>Input</header>
            <div className="body col">
              <textarea
                value={seq}
                onChange={(e) => setSeq(e.target.value)}
                placeholder="Paste DNA (FASTA header lines are ignored)…"
                style={{ minHeight: 220 }}
              />
              <div className="row tiny dim">
                <span>{formatNumber(clean.length)} bp</span>
                <span>GC {gcContent(clean)}%</span>
              </div>
              <div className="tabs">
                {(['scan', 'digest', 'orf', 'oligo', 'translate'] as Tool[]).map((t) => (
                  <button key={t} className={tool === t ? 'active' : ''} onClick={() => setTool(t)}>
                    {t === 'scan' ? 'Sites' : t === 'digest' ? 'Digest' : t === 'orf' ? 'ORFs' : t === 'oligo' ? 'Oligo QC' : 'Translate'}
                  </button>
                ))}
              </div>
              {tool === 'digest' && (
                <label className="field">
                  Enzymes (comma separated)
                  <input value={enzymes} onChange={(e) => setEnzymes(e.target.value)} />
                </label>
              )}
              {tool !== 'translate' && (
                <button className="primary" onClick={run} disabled={!clean || busy}>
                  {busy ? 'Running…' : 'Run'}
                </button>
              )}
            </div>
          </div>

          <div className="card">
            <header>Result</header>
            <div className="body">
              {busy && <Spinner />}

              {tool === 'translate' && (
                <div className="col">
                  {!clean && <Empty>Paste a sequence to translate.</Empty>}
                  {clean && (
                    <>
                      {[0, 1, 2].map((frame) => (
                        <div key={frame} className="col" style={{ gap: 2 }}>
                          <span className="tiny dim">frame +{frame + 1}</span>
                          <code className="tiny mono" style={{ wordBreak: 'break-all' }}>
                            {translate(clean.slice(frame)) || '—'}
                          </code>
                        </div>
                      ))}
                      {[0, 1, 2].map((frame) => (
                        <div key={`r${frame}`} className="col" style={{ gap: 2 }}>
                          <span className="tiny dim">frame −{frame + 1}</span>
                          <code className="tiny mono" style={{ wordBreak: 'break-all' }}>
                            {translate(reverseComplement(clean).slice(frame)) || '—'}
                          </code>
                        </div>
                      ))}
                    </>
                  )}
                </div>
              )}

              {tool === 'scan' && scan && (
                <table>
                  <thead>
                    <tr>
                      <th>Enzyme</th>
                      <th>Site</th>
                      <th className="num">Cuts</th>
                      <th>Positions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scan.summary.map((r) => (
                      <tr key={r.enzyme}>
                        <td>{r.enzyme}</td>
                        <td className="mono tiny">{r.display_site}</td>
                        <td className="num">{r.count}</td>
                        <td className="tiny dim truncate">{r.cut_positions.map((p) => p + 1).join(', ')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {tool === 'digest' && digest && (
                <div className="col">
                  <div className="small muted">
                    {digest.fragments.length} fragments: {digest.fragment_sizes.join(' / ')} bp
                  </div>
                  {digest.unknown_enzymes.length > 0 && (
                    <div className="tag warn">unknown: {digest.unknown_enzymes.join(', ')}</div>
                  )}
                  <GelView gel={digest.gel} height={260} />
                </div>
              )}

              {tool === 'orf' && orfs && (
                <table>
                  <thead>
                    <tr>
                      <th className="num">Start</th>
                      <th className="num">End</th>
                      <th>Strand</th>
                      <th className="num">aa</th>
                      <th>Protein (start)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orfs.slice(0, 30).map((o, i) => (
                      <tr key={i}>
                        <td className="num">{formatNumber(o.start + 1)}</td>
                        <td className="num">{formatNumber(o.end)}</td>
                        <td>{o.strand === 1 ? '+' : '−'}</td>
                        <td className="num">{o.aa_length}</td>
                        <td className="mono tiny truncate" style={{ maxWidth: 200 }}>
                          {o.protein.slice(0, 40)}…
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {tool === 'oligo' && oligo && (
                <dl className="kv">
                  <dt>Length</dt><dd>{oligo.length} nt</dd>
                  <dt>Tm</dt><dd>{oligo.tm} °C</dd>
                  <dt>GC</dt><dd>{oligo.gc}%</dd>
                  <dt>ΔG</dt><dd>{oligo.dg} kcal/mol</dd>
                  <dt>Hairpin</dt><dd>{oligo.hairpin_score}</dd>
                  <dt>Self-dimer</dt><dd>{oligo.self_dimer_score}</dd>
                  <dt>Warnings</dt><dd>{oligo.warnings.join('; ') || 'none'}</dd>
                </dl>
              )}

              {!busy && !scan && !digest && !orfs && !oligo && tool !== 'translate' && (
                <Empty>Paste a sequence and press Run.</Empty>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

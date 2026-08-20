/** Restriction enzymes: site table, selection, digest + virtual gel, pair suggestions. */
import { useEffect, useMemo, useState } from 'react'
import { api } from '@/api/client'
import type { DigestResult, EnzymeScanResult, SequenceDetail } from '@/api/types'
import { formatNumber } from '@/lib/seq'
import { reportError } from '@/store/auth'
import GelView from '../GelView'
import { Empty, Spinner } from '../Ui'

interface Props {
  sequence: SequenceDetail
  activeEnzymes: string[]
  onActiveEnzymesChange: (names: string[]) => void
  scan: EnzymeScanResult | null
  scanning: boolean
  onRescan: (commonOnly: boolean, uniqueOnly: boolean) => void
}

export default function EnzymePanel({ sequence, activeEnzymes, onActiveEnzymesChange, scan, scanning, onRescan }: Props) {
  const [commonOnly, setCommonOnly] = useState(true)
  const [uniqueOnly, setUniqueOnly] = useState(false)
  const [filter, setFilter] = useState('')
  const [digest, setDigest] = useState<DigestResult | null>(null)
  const [digesting, setDigesting] = useState(false)
  const [ladder, setLadder] = useState('1kb_plus')

  useEffect(() => {
    onRescan(commonOnly, uniqueOnly)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commonOnly, uniqueOnly, sequence.id, sequence.current_version])

  const rows = useMemo(() => {
    const list = scan?.summary ?? []
    return filter ? list.filter((r) => r.enzyme.toLowerCase().includes(filter.toLowerCase())) : list
  }, [scan, filter])

  const toggle = (name: string) => {
    onActiveEnzymesChange(
      activeEnzymes.includes(name) ? activeEnzymes.filter((n) => n !== name) : [...activeEnzymes, name],
    )
  }

  const runDigest = async () => {
    if (activeEnzymes.length === 0) return
    setDigesting(true)
    try {
      setDigest(await api.digest({ sequence_id: sequence.id, enzymes: activeEnzymes, ladder }))
    } catch (e) {
      reportError(e)
    } finally {
      setDigesting(false)
    }
  }

  return (
    <div className="col">
      <div className="row">
        <input placeholder="Filter enzymes…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ flex: 1 }} />
        <label className="inline">
          <input type="checkbox" checked={commonOnly} onChange={(e) => setCommonOnly(e.target.checked)} /> common
        </label>
        <label className="inline">
          <input type="checkbox" checked={uniqueOnly} onChange={(e) => setUniqueOnly(e.target.checked)} /> unique only
        </label>
      </div>

      {scanning && <Spinner label="Scanning sites…" />}

      {!scanning && rows.length === 0 && <Empty>No sites found for this filter.</Empty>}

      {rows.length > 0 && (
        <div style={{ maxHeight: 260, overflow: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th style={{ width: 24 }} />
                <th>Enzyme</th>
                <th>Site</th>
                <th className="num">Cuts</th>
                <th>Positions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.enzyme} className={activeEnzymes.includes(r.enzyme) ? 'selected' : ''}>
                  <td>
                    <input type="checkbox" checked={activeEnzymes.includes(r.enzyme)} onChange={() => toggle(r.enzyme)} />
                  </td>
                  <td>
                    {r.enzyme}
                    {r.unique && <span className="tag ok" style={{ marginLeft: 6 }}>1×</span>}
                  </td>
                  <td className="mono tiny">{r.display_site}</td>
                  <td className="num">{r.count}</td>
                  <td className="mono tiny dim truncate" title={r.cut_positions.map((p) => p + 1).join(', ')}>
                    {r.cut_positions.slice(0, 6).map((p) => p + 1).join(', ')}
                    {r.cut_positions.length > 6 ? '…' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="row">
        <select value={ladder} onChange={(e) => setLadder(e.target.value)} style={{ width: 150 }}>
          <option value="1kb_plus">1 kb Plus ladder</option>
          <option value="1kb">1 kb ladder</option>
          <option value="100bp">100 bp ladder</option>
          <option value="lambda_hindiii">λ HindIII</option>
        </select>
        <button className="primary" onClick={runDigest} disabled={activeEnzymes.length === 0 || digesting}>
          Digest with {activeEnzymes.length || 0} enzyme{activeEnzymes.length === 1 ? '' : 's'}
        </button>
        {activeEnzymes.length > 0 && (
          <button className="ghost sm" onClick={() => onActiveEnzymesChange([])}>
            clear
          </button>
        )}
      </div>

      {digesting && <Spinner label="Digesting…" />}

      {digest && (
        <div className="col">
          <div className="row small muted">
            <span>
              <b>{digest.fragments.length}</b> fragments
            </span>
            <span>·</span>
            <span className="mono tiny">{digest.fragment_sizes.join(' / ')} bp</span>
          </div>
          <GelView gel={digest.gel} />
          <table>
            <thead>
              <tr>
                <th className="num">#</th>
                <th className="num">Size</th>
                <th>Left</th>
                <th>Right</th>
                <th>Overhangs</th>
                <th className="num">GC%</th>
              </tr>
            </thead>
            <tbody>
              {digest.fragments.map((f, i) => (
                <tr key={i}>
                  <td className="num">{i + 1}</td>
                  <td className="num">{formatNumber(f.length)}</td>
                  <td className="tiny">{f.left_enzyme ?? '—'}</td>
                  <td className="tiny">{f.right_enzyme ?? '—'}</td>
                  <td className="mono tiny">
                    {f.left_overhang || '·'} / {f.right_overhang || '·'}
                  </td>
                  <td className="num">{f.gc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {scan && scan.suggestions.length > 0 && (
        <details>
          <summary className="small muted">Suggested cloning pairs (single cutters)</summary>
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th className="num">Distance</th>
                <th>Overhangs</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {scan.suggestions.slice(0, 12).map((s, i) => (
                <tr key={i}>
                  <td>
                    {s.enzyme_a} + {s.enzyme_b} {s.directional && <span className="tag info">directional</span>}
                  </td>
                  <td className="num">{formatNumber(s.distance)}</td>
                  <td className="mono tiny">
                    {s.overhang_a || 'blunt'} / {s.overhang_b || 'blunt'}
                  </td>
                  <td className="right">
                    <button className="ghost sm" onClick={() => onActiveEnzymesChange([s.enzyme_a, s.enzyme_b])}>
                      use
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  )
}

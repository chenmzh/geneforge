/**
 * Linear sequence viewer: wrapped rows with a ruler, both strands, optional
 * three-frame translation, feature lanes, enzyme cut marks, drag selection and
 * row virtualisation so a 100 kb construct still scrolls smoothly.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { EnzymeSite, Feature } from '@/api/types'
import { complement, contrastText, featureColor, packLanes, translate, type Hit } from '@/lib/seq'

export interface Selection { start: number; end: number }

interface Props {
  sequence: string
  features: Feature[]
  sites?: EnzymeSite[]
  hits?: Hit[]
  selection: Selection | null
  onSelectionChange: (sel: Selection | null) => void
  selectedFeatureId?: string | null
  onFeatureClick?: (feature: Feature) => void
  showComplement?: boolean
  showTranslation?: boolean
  showFeatures?: boolean
  showEnzymes?: boolean
  fontSize?: number
}

const GUTTER = 76
const PADDING = 28

export default function SequenceViewer({
  sequence,
  features,
  sites = [],
  hits = [],
  selection,
  onSelectionChange,
  selectedFeatureId,
  onFeatureClick,
  showComplement = true,
  showTranslation = false,
  showFeatures = true,
  showEnzymes = true,
  fontSize = 12.5,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const measureRef = useRef<HTMLSpanElement>(null)
  const [charWidth, setCharWidth] = useState(7.6)
  const [width, setWidth] = useState(900)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(600)
  const dragging = useRef<{ anchor: number } | null>(null)

  // measure the monospace advance so base columns line up with overlays
  useLayoutEffect(() => {
    if (measureRef.current) {
      const w = measureRef.current.getBoundingClientRect().width / 100
      if (w > 0) setCharWidth(w)
    }
  }, [fontSize])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setWidth(el.clientWidth)
      setViewportH(el.clientHeight)
    })
    ro.observe(el)
    setWidth(el.clientWidth)
    setViewportH(el.clientHeight)
    return () => ro.disconnect()
  }, [])

  const perRow = Math.max(20, Math.floor((width - GUTTER - PADDING) / charWidth / 10) * 10)
  const rowCount = Math.max(1, Math.ceil(sequence.length / perRow))

  const featureLanes = useMemo(
    () => (showFeatures ? packLanes(features, 6) : []),
    [features, showFeatures],
  )

  const lineH = Math.round(fontSize * 1.36)
  const rowHeight =
    14 + // ruler
    lineH +
    (showComplement ? lineH : 0) +
    (showTranslation ? lineH * 3 : 0) +
    (showEnzymes ? 16 : 0) +
    featureLanes.length * 15 +
    10

  const first = Math.max(0, Math.floor(scrollTop / rowHeight) - 2)
  const last = Math.min(rowCount, Math.ceil((scrollTop + viewportH) / rowHeight) + 2)

  const sitesByRow = useMemo(() => {
    const map = new Map<number, EnzymeSite[]>()
    if (!showEnzymes) return map
    for (const site of sites) {
      const row = Math.floor(site.cut_top / perRow)
      const list = map.get(row)
      if (list) list.push(site)
      else map.set(row, [site])
    }
    return map
  }, [sites, perRow, showEnzymes])

  const selNorm = selection ? { start: Math.min(selection.start, selection.end), end: Math.max(selection.start, selection.end) } : null

  const indexFromEvent = useCallback(
    (event: React.MouseEvent): number | null => {
      const target = event.target as HTMLElement
      const idx = target.dataset?.idx
      if (idx !== undefined) return Number(idx)
      const row = target.closest<HTMLElement>('[data-row]')
      if (!row) return null
      const bases = row.querySelector<HTMLElement>('[data-bases]')
      if (!bases) return null
      const rect = bases.getBoundingClientRect()
      const rowStart = Number(row.dataset.row) * perRow
      const offset = Math.round((event.clientX - rect.left) / charWidth)
      return Math.max(rowStart, Math.min(sequence.length, rowStart + offset))
    },
    [charWidth, perRow, sequence.length],
  )

  const onMouseDown = (event: React.MouseEvent) => {
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    if (target.closest('.feature-chip')) return
    const idx = indexFromEvent(event)
    if (idx === null) return
    dragging.current = { anchor: idx }
    onSelectionChange({ start: idx, end: idx })
  }

  const onMouseMove = (event: React.MouseEvent) => {
    if (!dragging.current) return
    const idx = indexFromEvent(event)
    if (idx === null) return
    onSelectionChange({ start: dragging.current.anchor, end: idx })
  }

  const onMouseUp = (event: React.MouseEvent) => {
    if (!dragging.current) return
    const idx = indexFromEvent(event)
    const anchor = dragging.current.anchor
    dragging.current = null
    if (idx === null || idx === anchor) onSelectionChange({ start: anchor, end: anchor })
    else onSelectionChange({ start: anchor, end: idx })
  }

  useEffect(() => {
    const stop = () => { dragging.current = null }
    window.addEventListener('mouseup', stop)
    return () => window.removeEventListener('mouseup', stop)
  }, [])

  const renderBases = (text: string, rowStart: number, kind: 'fwd' | 'rc') => {
    const nodes: React.ReactNode[] = []
    let run = ''
    let runClass = ''
    let runStart = 0
    const classFor = (globalIdx: number): string => {
      let cls = ''
      if (selNorm && globalIdx >= selNorm.start && globalIdx < selNorm.end) cls += ' base-sel'
      else if (hits.some((h) => globalIdx >= h.start && globalIdx < h.end)) cls += ' base-hit'
      return cls.trim()
    }
    const flush = (endIdx: number) => {
      if (!run) return
      nodes.push(
        <span key={`${kind}-${runStart}`} className={`b ${runClass}`} data-idx={runStart}>
          {run}
        </span>,
      )
      run = ''
      runStart = endIdx
    }
    for (let i = 0; i < text.length; i++) {
      const cls = classFor(rowStart + i)
      if (cls !== runClass) {
        flush(rowStart + i)
        runClass = cls
        runStart = rowStart + i
      }
      run += text[i]
    }
    flush(rowStart + text.length)
    return nodes
  }

  const rows: React.ReactNode[] = []
  for (let row = first; row < last; row++) {
    const rowStart = row * perRow
    const rowEnd = Math.min(sequence.length, rowStart + perRow)
    const fwd = sequence.slice(rowStart, rowEnd)
    if (!fwd) continue

    // ruler: a tick label every 10 bases
    let ruler = ''
    for (let i = 0; i < fwd.length; i += 10) {
      const label = String(rowStart + i + 10)
      const cell = ' '.repeat(Math.max(0, 10 - label.length)) + label
      ruler += cell
    }

    const rowSites = sitesByRow.get(row) ?? []

    rows.push(
      <div
        key={row}
        className="seq-row"
        data-row={row}
        style={{ position: 'absolute', top: row * rowHeight, left: 0, right: 0, height: rowHeight }}
      >
        <div className="seq-line ruler">
          <span className="gutter" />
          <span className="bases">{ruler}</span>
        </div>

        {showEnzymes && (
          <div className="enzyme-track">
            <span className="gutter" />
            <span className="lane">
              {rowSites.slice(0, 26).map((site, i) => (
                <span
                  key={`${site.enzyme}-${site.cut_top}-${i}`}
                  className="enzyme-mark"
                  style={{ left: (site.cut_top - rowStart) * charWidth, top: i % 2 === 0 ? 0 : 7 }}
                  title={`${site.enzyme} cut ${site.cut_top + 1} (${site.overhang})`}
                >
                  {site.enzyme}
                  <i />
                </span>
              ))}
            </span>
          </div>
        )}

        <div className="seq-line">
          <span className="gutter">{rowStart + 1}</span>
          <span className="bases" data-bases>
            {renderBases(fwd, rowStart, 'fwd')}
          </span>
        </div>

        {showComplement && (
          <div className="seq-line rc">
            <span className="gutter" />
            <span className="bases">{renderBases(complement(fwd), rowStart, 'rc')}</span>
          </div>
        )}

        {showTranslation &&
          [0, 1, 2].map((frame) => {
            const startOffset = (frame - (rowStart % 3) + 3) % 3
            const slice = sequence.slice(rowStart + startOffset, rowEnd)
            const protein = translate(slice)
            const spaced = protein.split('').map((aa) => ` ${aa} `).join('')
            return (
              <div className="seq-line aa" key={`aa-${frame}`}>
                <span className="gutter tiny">f{frame + 1}</span>
                <span className="bases" style={{ marginLeft: startOffset * charWidth }}>
                  {spaced}
                </span>
              </div>
            )
          })}

        {featureLanes.map((lane, laneIdx) => (
          <div className="feature-track" key={`lane-${laneIdx}`}>
            <span className="gutter" />
            <span className="lane">
              {lane
                .filter((f) => f.end > rowStart && f.start < rowEnd)
                .map((f) => {
                  const from = Math.max(f.start, rowStart)
                  const to = Math.min(f.end, rowEnd)
                  const w = Math.max(3, (to - from) * charWidth)
                  const bg = featureColor(f.type, f.color)
                  const label = f.strand === -1 ? `◄ ${f.name}` : `${f.name} ►`
                  return (
                    <span
                      key={f.id}
                      className={`feature-chip${selectedFeatureId === f.id ? ' selected' : ''}`}
                      style={{ left: (from - rowStart) * charWidth, width: w, background: bg, color: contrastText(bg) }}
                      title={`${f.name} · ${f.type} · ${f.start + 1}–${f.end} (${f.end - f.start} bp)`}
                      onClick={(e) => {
                        e.stopPropagation()
                        onFeatureClick?.(f)
                      }}
                    >
                      {w > 34 ? label : ''}
                    </span>
                  )
                })}
            </span>
          </div>
        ))}
      </div>,
    )
  }

  return (
    <div
      className="seq-scroll"
      ref={scrollRef}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
    >
      <span
        ref={measureRef}
        className="mono"
        style={{ position: 'absolute', visibility: 'hidden', whiteSpace: 'pre', fontSize, top: -9999 }}
      >
        {'M'.repeat(100)}
      </span>
      <div className="seq-canvas" style={{ height: rowCount * rowHeight + 40, fontSize }}>
        {rows}
      </div>
    </div>
  )
}

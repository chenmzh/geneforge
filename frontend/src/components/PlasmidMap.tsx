/**
 * Circular / linear plasmid map rendered as SVG: feature arcs with strand
 * arrowheads, enzyme cut ticks with leader lines, a GC ring, the current
 * selection arc and a clickable centre label.
 */
import { useMemo } from 'react'
import type { EnzymeSite, Feature } from '@/api/types'
import { featureColor, formatBp } from '@/lib/seq'
import type { Selection } from './SequenceViewer'

interface Props {
  name: string
  length: number
  topology: 'linear' | 'circular'
  features: Feature[]
  sites?: EnzymeSite[]
  gcTrack?: { start: number; end: number; gc: number }[]
  selection: Selection | null
  selectedFeatureId?: string | null
  onFeatureClick?: (feature: Feature) => void
  onPositionClick?: (position: number) => void
  size?: number
}

interface Ring { feature: Feature; ring: number }

const TAU = Math.PI * 2

export default function PlasmidMap({
  name,
  length,
  topology,
  features,
  sites = [],
  gcTrack = [],
  selection,
  selectedFeatureId,
  onFeatureClick,
  onPositionClick,
  size = 560,
}: Props) {
  const cx = size / 2
  const cy = size / 2
  // Reserve room for the longest enzyme label: labels sit radially outside the
  // ring and grow horizontally, so the ring has to shrink as labels get longer.
  const labelChars = sites.reduce((max, s) => Math.max(max, `${s.enzyme} (${s.cut_top + 1})`.length), 0)
  const labelPx = labelChars * 5.3
  const outer = Math.max(size * 0.16, Math.min(size * 0.34, size / 2 - labelPx - 44))
  const ringWidth = Math.max(8, Math.min(13, outer / 11))
  const labelRadius = outer + 18

  const angle = (pos: number) => (pos / Math.max(1, length)) * TAU - Math.PI / 2
  const point = (pos: number, radius: number) => {
    const a = angle(pos)
    return [cx + radius * Math.cos(a), cy + radius * Math.sin(a)] as const
  }

  // stack overlapping features onto concentric rings
  const rings = useMemo<Ring[]>(() => {
    const occupied: { start: number; end: number }[][] = []
    const out: Ring[] = []
    for (const f of [...features].sort((a, b) => b.end - b.start - (a.end - a.start))) {
      let ring = 0
      for (;;) {
        const lane = occupied[ring] ?? (occupied[ring] = [])
        const clash = lane.some((s) => f.start < s.end && f.end > s.start)
        if (!clash || ring >= 4) {
          lane.push({ start: f.start, end: f.end })
          break
        }
        ring++
      }
      out.push({ feature: f, ring })
    }
    return out
  }, [features])

  const arcPath = (start: number, end: number, radius: number, thickness: number, strand: number) => {
    const span = Math.max(end - start, Math.max(1, length / 900))
    const a0 = angle(start)
    const a1 = angle(start + span)
    const rOut = radius + thickness / 2
    const rIn = radius - thickness / 2
    const head = Math.min(Math.abs(a1 - a0) * 0.4, 0.09)
    const large = a1 - a0 > Math.PI ? 1 : 0
    const p = (r: number, a: number) => `${cx + r * Math.cos(a)} ${cy + r * Math.sin(a)}`

    if (strand === -1) {
      const aTip = a0
      const aBody = a0 + head
      return [
        `M ${p(radius, aTip)}`,
        `L ${p(rOut, aBody)}`,
        `A ${rOut} ${rOut} 0 ${large} 1 ${p(rOut, a1)}`,
        `L ${p(rIn, a1)}`,
        `A ${rIn} ${rIn} 0 ${large} 0 ${p(rIn, aBody)}`,
        'Z',
      ].join(' ')
    }
    const aTip = a1
    const aBody = a1 - head
    return [
      `M ${p(rOut, a0)}`,
      `A ${rOut} ${rOut} 0 ${large} 1 ${p(rOut, aBody)}`,
      `L ${p(radius, aTip)}`,
      `L ${p(rIn, aBody)}`,
      `A ${rIn} ${rIn} 0 ${large} 0 ${p(rIn, a0)}`,
      'Z',
    ].join(' ')
  }

  const selectionArc = () => {
    if (!selection) return null
    const start = Math.min(selection.start, selection.end)
    const end = Math.max(selection.start, selection.end)
    if (end - start < 1) return null
    const a0 = angle(start)
    const a1 = angle(end)
    const r = outer + 8
    const large = a1 - a0 > Math.PI ? 1 : 0
    const p = (radius: number, a: number) => `${cx + radius * Math.cos(a)} ${cy + radius * Math.sin(a)}`
    return (
      <path
        className="sel-arc"
        d={`M ${cx} ${cy} L ${p(r, a0)} A ${r} ${r} 0 ${large} 1 ${p(r, a1)} Z`}
      />
    )
  }

  // enzyme labels: alternate radius so dense clusters stay readable
  const cutLabels = useMemo(() => {
    const sorted = [...sites].sort((a, b) => a.cut_top - b.cut_top).slice(0, 60)
    return sorted.map((site, i) => {
      const a = angle(site.cut_top)
      const extra = (i % 3) * 11
      const r1 = outer + 4
      const r2 = labelRadius + extra
      const [x1, y1] = point(site.cut_top, r1 - 8)
      const [x2, y2] = point(site.cut_top, r2 - 6)
      const anchor: 'start' | 'end' | 'middle' = Math.cos(a) > 0.08 ? 'start' : Math.cos(a) < -0.08 ? 'end' : 'middle'
      const [lx, ly] = point(site.cut_top, r2)
      return { site, x1, y1, x2, y2, lx, ly, anchor }
    })
  }, [sites, length, outer])

  const ticks = useMemo(() => {
    const step = tickStep(length)
    const out: { pos: number; label: string }[] = []
    for (let pos = 0; pos < length; pos += step) out.push({ pos, label: pos === 0 ? '1' : String(pos) })
    return out
  }, [length])

  const handleBackgroundClick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!onPositionClick) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = event.clientX - rect.left - cx
    const y = event.clientY - rect.top - cy
    const radius = Math.hypot(x, y)
    if (radius < outer * 0.45 || radius > outer + 40) return
    let a = Math.atan2(y, x) + Math.PI / 2
    if (a < 0) a += TAU
    onPositionClick(Math.round((a / TAU) * length) % length)
  }

  return (
    <div className="plasmid">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} onClick={handleBackgroundClick}>
        {selectionArc()}

        {/* GC ring */}
        {gcTrack.length > 1 && (
          <g opacity={0.55}>
            {gcTrack.map((band, i) => {
              const mid = (band.start + band.end) / 2
              const r = outer * 0.62
              const h = ((band.gc - 25) / 50) * 12
              const [x1, y1] = point(mid, r)
              const [x2, y2] = point(mid, r + Math.max(-10, Math.min(12, h)))
              return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#2f6f8f" strokeWidth={1.2} />
            })}
          </g>
        )}

        {/* backbone */}
        {topology === 'circular' ? (
          <circle className="backbone" cx={cx} cy={cy} r={outer} strokeWidth={2.5} />
        ) : (
          <line className="backbone" x1={cx - outer} y1={cy} x2={cx + outer} y2={cy} strokeWidth={2.5} />
        )}

        {/* ruler ticks */}
        {topology === 'circular' &&
          ticks.map(({ pos, label }) => {
            const [x1, y1] = point(pos, outer - 5)
            const [x2, y2] = point(pos, outer + 5)
            const [tx, ty] = point(pos, outer - 16)
            return (
              <g key={pos}>
                <line className="tick" x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={1} />
                <text x={tx} y={ty} fill="#6b7d8f" fontSize={9} textAnchor="middle" dominantBaseline="middle">
                  {label}
                </text>
              </g>
            )
          })}

        {/* enzyme cut marks + labels */}
        {cutLabels.map(({ site, x1, y1, x2, y2, lx, ly, anchor }, i) => (
          <g key={`${site.enzyme}-${site.cut_top}-${i}`}>
            <line className="cut" x1={x1} y1={y1} x2={x2} y2={y2} strokeWidth={0.8} opacity={0.7} />
            <text x={lx} y={ly} fill="#f0908a" fontSize={9.5} textAnchor={anchor} dominantBaseline="middle">
              {site.enzyme} ({site.cut_top + 1})
            </text>
          </g>
        ))}

        {/* features */}
        {topology === 'circular'
          ? rings.map(({ feature, ring }) => {
              const radius = outer - ring * (ringWidth + 3)
              const color = featureColor(feature.type, feature.color)
              return (
                <path
                  key={feature.id}
                  className="feat"
                  d={arcPath(feature.start, feature.end, radius, ringWidth, feature.strand)}
                  fill={color}
                  stroke={selectedFeatureId === feature.id ? '#fff' : 'rgba(0,0,0,.35)'}
                  strokeWidth={selectedFeatureId === feature.id ? 1.6 : 0.6}
                  onClick={(e) => {
                    e.stopPropagation()
                    onFeatureClick?.(feature)
                  }}
                >
                  <title>{`${feature.name} · ${feature.type} · ${feature.start + 1}–${feature.end}`}</title>
                </path>
              )
            })
          : rings.map(({ feature, ring }) => {
              const x = cx - outer + (feature.start / Math.max(1, length)) * outer * 2
              const w = Math.max(2, ((feature.end - feature.start) / Math.max(1, length)) * outer * 2)
              const y = cy + 8 + ring * 16
              const color = featureColor(feature.type, feature.color)
              return (
                <g key={feature.id} className="feat" onClick={(e) => { e.stopPropagation(); onFeatureClick?.(feature) }}>
                  <rect x={x} y={y} width={w} height={12} rx={2} fill={color} stroke="rgba(0,0,0,.35)" />
                  <text x={x + w + 4} y={y + 6} fontSize={9.5} fill="#9fb0c0" dominantBaseline="middle">
                    {feature.name}
                  </text>
                </g>
              )
            })}

        {/* feature labels around the ring */}
        {topology === 'circular' &&
          rings
            .filter(({ feature }) => (feature.end - feature.start) / Math.max(1, length) > 0.035)
            .map(({ feature, ring }) => {
              const mid = (feature.start + feature.end) / 2
              const radius = outer - ring * (ringWidth + 3)
              const [tx, ty] = point(mid, radius)
              const color = featureColor(feature.type, feature.color)
              return (
                <text
                  key={`label-${feature.id}`}
                  x={tx}
                  y={ty}
                  fontSize={9}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill={luminance(color) > 150 ? '#0b1218' : '#f2f7fb'}
                  pointerEvents="none"
                >
                  {feature.name.length > 18 ? `${feature.name.slice(0, 17)}…` : feature.name}
                </text>
              )
            })}

        {/* centre label */}
        <text className="center-name" x={cx} y={cy - 6} textAnchor="middle">
          {name.length > 26 ? `${name.slice(0, 25)}…` : name}
        </text>
        <text className="center-sub" x={cx} y={cy + 12} textAnchor="middle">
          {formatBp(length)} · {topology}
        </text>
        {selection && Math.abs(selection.end - selection.start) > 0 && (
          <text className="center-sub" x={cx} y={cy + 28} textAnchor="middle" fill="#4f8ef7">
            {Math.min(selection.start, selection.end) + 1}–{Math.max(selection.start, selection.end)} (
            {Math.abs(selection.end - selection.start)} bp)
          </text>
        )}
      </svg>
    </div>
  )
}

function tickStep(length: number): number {
  const raw = length / 12
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(1, raw)))
  for (const factor of [1, 2, 5, 10]) {
    if (magnitude * factor >= raw) return magnitude * factor
  }
  return magnitude * 10
}

function luminance(hex: string): number {
  const clean = hex.replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean.slice(0, 6)
  const r = parseInt(full.slice(0, 2), 16) || 0
  const g = parseInt(full.slice(2, 4), 16) || 0
  const b = parseInt(full.slice(4, 6), 16) || 0
  return 0.299 * r + 0.587 * g + 0.114 * b
}

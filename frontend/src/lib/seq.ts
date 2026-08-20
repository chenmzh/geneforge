/** Client-side sequence helpers (kept dependency-free and pure). */

const COMPLEMENT: Record<string, string> = {
  A: 'T', T: 'A', G: 'C', C: 'G', U: 'A', N: 'N', R: 'Y', Y: 'R', S: 'S', W: 'W',
  K: 'M', M: 'K', B: 'V', V: 'B', D: 'H', H: 'D', '-': '-',
}

export function complement(seq: string): string {
  let out = ''
  for (const ch of seq.toUpperCase()) out += COMPLEMENT[ch] ?? 'N'
  return out
}

export function reverseComplement(seq: string): string {
  return complement(seq).split('').reverse().join('')
}

export function gcContent(seq: string): number {
  if (!seq) return 0
  let gc = 0
  for (const ch of seq.toUpperCase()) if (ch === 'G' || ch === 'C' || ch === 'S') gc++
  return Math.round((1000 * gc) / seq.length) / 10
}

/** Wallace / GC-based Tm approximation for the selection readout. */
export function quickTm(seq: string): number {
  const n = seq.length
  if (n === 0) return 0
  const gc = (gcContent(seq) / 100) * n
  if (n < 14) return Math.round((2 * (n - gc) + 4 * gc) * 10) / 10
  return Math.round((64.9 + (41 * (gc - 16.4)) / n) * 10) / 10
}

const CODONS: Record<string, string> = {}
{
  const bases = 'TCAG'
  const aas = 'FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG'
  let i = 0
  for (const b1 of bases) for (const b2 of bases) for (const b3 of bases) CODONS[b1 + b2 + b3] = aas[i++]
}

export function translate(seq: string): string {
  const s = seq.toUpperCase().replace(/U/g, 'T')
  let out = ''
  for (let i = 0; i + 3 <= s.length; i += 3) out += CODONS[s.slice(i, i + 3)] ?? 'X'
  return out
}

export function formatBp(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)} Mb`
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 1 : 2)} kb`
  return `${n} bp`
}

export function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

/** Deterministic colour for a feature type when no explicit colour is set. */
const TYPE_COLORS: Record<string, string> = {
  CDS: '#4f8ef7',
  gene: '#5bc0a8',
  promoter: '#f5a623',
  terminator: '#d0021b',
  rep_origin: '#9b59b6',
  primer_bind: '#16a085',
  misc_feature: '#7f8c8d',
  RBS: '#e67e22',
  polyA_signal: '#c0392b',
  protein_bind: '#8e44ad',
  regulatory: '#f39c12',
  LTR: '#2c3e50',
  source: '#546e7a',
  sig_peptide: '#e84393',
}

export function featureColor(type: string, explicit?: string | null): string {
  if (explicit && /^#[0-9a-f]{3,8}$/i.test(explicit)) return explicit
  return TYPE_COLORS[type] ?? '#7f8c8d'
}

export function contrastText(hex: string): string {
  const clean = hex.replace('#', '')
  const full = clean.length === 3 ? clean.split('').map((c) => c + c).join('') : clean.slice(0, 6)
  const r = parseInt(full.slice(0, 2), 16)
  const g = parseInt(full.slice(2, 4), 16)
  const b = parseInt(full.slice(4, 6), 16)
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#0b1218' : '#f2f7fb'
}

/** Find matches of a (possibly IUPAC) pattern, both strands, for the search box. */
const IUPAC: Record<string, string> = {
  A: 'A', C: 'C', G: 'G', T: 'T', U: 'T', R: 'AG', Y: 'CT', S: 'CG', W: 'AT',
  K: 'GT', M: 'AC', B: 'CGT', D: 'AGT', H: 'ACT', V: 'ACG', N: 'ACGT',
}

export function iupacRegex(pattern: string): RegExp | null {
  let body = ''
  for (const ch of pattern.toUpperCase()) {
    const set = IUPAC[ch]
    if (!set) return null
    body += set.length === 1 ? set : `[${set}]`
  }
  return body ? new RegExp(body, 'gi') : null
}

export interface Hit { start: number; end: number; strand: number }

export function findMatches(sequence: string, pattern: string, bothStrands = true): Hit[] {
  const hits: Hit[] = []
  if (!pattern || pattern.length < 2) return hits
  const fwd = iupacRegex(pattern)
  if (!fwd) return hits
  for (const m of sequence.matchAll(fwd)) {
    if (m.index === undefined) continue
    hits.push({ start: m.index, end: m.index + m[0].length, strand: 1 })
  }
  if (bothStrands) {
    const rc = iupacRegex(reverseComplement(pattern))
    if (rc && reverseComplement(pattern) !== pattern.toUpperCase()) {
      for (const m of sequence.matchAll(rc)) {
        if (m.index === undefined) continue
        hits.push({ start: m.index, end: m.index + m[0].length, strand: -1 })
      }
    }
  }
  return hits.sort((a, b) => a.start - b.start)
}

/** Assign features to non-overlapping display lanes. */
export function packLanes<T extends { start: number; end: number }>(items: T[], maxLanes = 8): T[][] {
  const lanes: T[][] = []
  for (const item of [...items].sort((a, b) => a.start - b.start || b.end - a.end)) {
    let placed = false
    for (const lane of lanes) {
      const last = lane[lane.length - 1]
      if (item.start >= last.end) {
        lane.push(item)
        placed = true
        break
      }
    }
    if (!placed) {
      if (lanes.length >= maxLanes) lanes[lanes.length - 1].push(item)
      else lanes.push([item])
    }
  }
  return lanes
}

export function downloadText(filename: string, text: string, type = 'text/plain') {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

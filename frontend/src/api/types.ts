/** Types mirroring the FastAPI schemas (backend/app/schemas). */

export interface Page<T> { items: T[]; total: number; page: number; size: number; pages: number }

export interface User {
  id: string
  email: string
  username: string
  full_name?: string | null
  role: 'admin' | 'editor' | 'viewer'
  is_active: boolean
  created_at: string
  last_login_at?: string | null
}

export interface Token { access_token: string; refresh_token: string; token_type: string; expires_in: number }

export interface Project {
  id: string
  name: string
  slug: string
  description?: string | null
  owner_id: string
  is_archived: boolean
  tags: string[]
  created_at: string
  updated_at: string
  sequence_count: number
  my_role?: string | null
  members?: Member[]
  metadata?: Record<string, unknown>
}

export interface Member { id: string; user_id: string; role: string; username?: string; email?: string }

export interface Feature {
  id: string
  sequence_id: string
  type: string
  name: string
  start: number
  end: number
  strand: number
  color?: string | null
  segments: number[][]
  qualifiers: Record<string, unknown>
}

export interface SequenceSummary {
  id: string
  project_id: string
  name: string
  description?: string | null
  seq_type: string
  topology: 'linear' | 'circular'
  molecule_type: string
  length: number
  gc_content: number
  current_version: number
  source_format: string
  checksum: string
  created_at: string
  updated_at: string
  feature_count: number
}

export interface SequenceDetail extends SequenceSummary {
  sequence: string
  features: Feature[]
  annotations: Record<string, unknown>
}

export interface SequenceVersion {
  id: string
  sequence_id: string
  version: number
  message: string
  topology: string
  created_at: string
  created_by_id?: string | null
  diff_summary: Record<string, unknown>
  length: number
}

export interface SequenceStats {
  length: number
  gc: number
  topology: string
  a: number; c: number; g: number; t: number
  ambiguous: number
  orf_count: number
  longest_orf?: Record<string, unknown> | null
  gc_track: { start: number; end: number; gc: number }[]
  molecular_weight: number
  melting_temp: number
}

export interface EnzymeInfo {
  name: string
  site: string
  display_site: string
  fwd_cut: number
  rev_cut: number
  overhang: string
  overhang_length: number
  palindromic: boolean
  type_iis: boolean
  suppliers: string
  common: boolean
}

export interface EnzymeSite {
  enzyme: string
  position: number
  start: number
  end: number
  strand: number
  cut_top: number
  cut_bottom: number
  site_seq: string
  overhang: string
  overhang_seq: string
}

export interface EnzymeSummaryRow {
  enzyme: string
  site: string
  display_site: string
  overhang: string
  count: number
  positions: number[]
  cut_positions: number[]
  unique: boolean
  common: boolean
}

export interface EnzymeScanResult {
  sites: EnzymeSite[]
  summary: EnzymeSummaryRow[]
  suggestions: {
    enzyme_a: string; enzyme_b: string; cut_a: number; cut_b: number
    distance: number; overhang_a: string; overhang_b: string; directional: boolean; score: number
  }[]
}

export interface Fragment {
  start: number; end: number; length: number; gc: number
  left_enzyme?: string | null; right_enzyme?: string | null
  left_overhang: string; right_overhang: string
  crosses_origin: boolean
  sequence_preview: string
}

export interface GelBand { size: number; migration: number; intensity: number; kind: string }
export interface Gel { ladder: string; gel_percent?: number; lanes: { name: string; bands: GelBand[] }[] }

export interface DigestResult {
  length: number
  topology: string
  enzymes: EnzymeInfo[]
  unknown_enzymes: string[]
  sites: EnzymeSite[]
  cut_positions: number[]
  fragments: Fragment[]
  fragment_sizes: number[]
  site_counts: Record<string, number>
  gel: Gel
  ligation?: { donor: number; acceptor: number; overhang: string; blunt: boolean }[]
}

export interface PrimerStats {
  sequence: string
  length: number
  tm: number
  gc: number
  dh: number
  ds: number
  dg: number
  gc_clamp: boolean
  max_homopolymer: number
  hairpin_score: number
  self_dimer_score: number
  end_stability: number
  degenerate: boolean
  warnings: string[]
}

export interface PrimerPair {
  forward: PrimerStats & { name: string; start: number; end: number; strand: number }
  reverse: PrimerStats & { name: string; start: number; end: number; strand: number }
  product_start: number
  product_end: number
  product_size: number
  product_gc: number
  tm_difference: number
  pair_dimer_score: number
  covers_target: boolean
  annealing_temp: number
  score: number
  forward_full?: PrimerStats
  reverse_full?: PrimerStats
}

export interface PcrResult {
  forward: PrimerStats | null
  reverse: PrimerStats | null
  forward_sites: { strand: number; start: number; end: number; mismatches: number; tm: number }[]
  reverse_sites: { strand: number; start: number; end: number; mismatches: number; tm: number }[]
  forward_site_count: number
  reverse_site_count: number
  products: {
    start: number; end: number; size: number; crosses_origin: boolean
    gc: number; tm_product: number; forward_mismatches: number; reverse_mismatches: number; sequence: string
  }[]
  specific: boolean
  annealing_temp: number | null
  warnings: string[]
  pair_dimer_score: number
}

export interface Variant { kind: string; ref_pos: number; query_pos: number; ref: string; query: string }

export interface AlignResult {
  method: string
  mode: string
  score: number
  identity: number
  similarity: number
  gaps: number
  length: number
  aligned_query: string
  aligned_target: string
  midline: string
  truncated: boolean
  query_start: number
  query_end: number
  target_start: number
  target_end: number
  strand: number
  cigar: string
  variants: Variant[]
  variant_count: number
  blocks: Record<string, number>[]
}

export interface MsaResult {
  reference: string
  width: number
  rows: { name: string; aligned: string }[]
  consensus: string
  conservation: number[]
  identity_matrix: { a: string; b: string; identity: number }[]
}

export interface Orf {
  start: number; end: number; strand: number; frame: number; length: number
  aa_length: number; protein: string; start_codon: string; stop_codon: string; crosses_origin: boolean
}

export interface Job {
  id: string
  project_id?: string | null
  type: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  progress: number
  params: Record<string, unknown>
  result?: Record<string, unknown> | null
  error?: string | null
  backend: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface StoredPrimer {
  id: string
  project_id: string
  sequence_id?: string | null
  name: string
  sequence: string
  tm?: number | null
  gc_content?: number | null
  binding_start?: number | null
  binding_end?: number | null
  strand: number
  notes?: string | null
  stats: Record<string, unknown>
  created_at: string
}

export interface ExternalResource {
  id: string
  name: string
  kind: 'link' | 'rest' | 'blast'
  description?: string | null
  url_template: string
  method: string
  query_defaults: Record<string, unknown>
  allow_proxy: boolean
  is_enabled: boolean
  created_at: string
}

export interface Capabilities {
  app: string
  version: string
  environment: string
  import_formats: string[]
  export_formats: string[]
  enzyme_catalogue_size: number
  queue_backend: string
  registration_open: boolean
  external_proxy_enabled: boolean
  max_sequence_length: number
  max_upload_bytes: number
}

export interface DashboardSummary {
  projects: number
  sequences: number
  active_jobs: number
  recent_sequences: { id: string; name: string; project_id: string; length: number; topology: string; updated_at: string | null }[]
}

export interface ImportResult {
  imported: { sequence_id: string; name: string; length: number; topology: string; feature_count: number; source_format: string }[]
  skipped: { name?: string; reason?: string }[]
  detected_format: string
  file_id?: string | null
}

export interface AuditEntry {
  id: string
  created_at: string
  user_id?: string | null
  action: string
  entity_type?: string | null
  entity_id?: string | null
  ip_address?: string | null
  detail: Record<string, unknown>
}

export type EditOp =
  | { op: 'insert'; position: number; payload: string }
  | { op: 'delete'; start: number; end: number }
  | { op: 'replace'; start: number; end: number; payload: string }
  | { op: 'reverse_complement' }
  | { op: 'reverse_complement_range'; start: number; end: number }
  | { op: 'set_origin'; origin: number }
  | { op: 'set_topology'; topology: 'linear' | 'circular' }

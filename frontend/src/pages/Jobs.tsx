/** Jobs monitor: poll the queue, inspect results, cancel/delete. */
import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Job } from '@/api/types'
import { Empty, Modal, Spinner } from '@/components/Ui'
import { reportError } from '@/store/auth'

const STATUS_TAG: Record<Job['status'], string> = {
  pending: 'tag',
  running: 'tag info',
  succeeded: 'tag ok',
  failed: 'tag err',
  cancelled: 'tag warn',
}

export default function Jobs() {
  const qc = useQueryClient()
  const [inspect, setInspect] = useState<Job | null>(null)
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => api.jobs(), refetchInterval: 2500 })

  return (
    <>
      <div className="topbar">
        <h1>Jobs</h1>
        <span className="spacer" />
        <button onClick={() => qc.invalidateQueries({ queryKey: ['jobs'] })}>refresh</button>
      </div>
      <div className="content">
        {jobs.isLoading && <Spinner />}
        {jobs.data?.items.length === 0 && (
          <Empty>
            No jobs yet. Long alignments, whole-catalogue enzyme scans and large primer designs are queued here
            automatically.
          </Empty>
        )}
        {(jobs.data?.items.length ?? 0) > 0 && (
          <div className="card">
            <div className="body">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Progress</th>
                    <th>Backend</th>
                    <th>Created</th>
                    <th>Duration</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {jobs.data?.items.map((job) => {
                    const started = job.started_at ? new Date(job.started_at).getTime() : null
                    const finished = job.finished_at ? new Date(job.finished_at).getTime() : null
                    return (
                      <tr key={job.id}>
                        <td>{job.type}</td>
                        <td>
                          <span className={STATUS_TAG[job.status]}>{job.status}</span>
                        </td>
                        <td style={{ minWidth: 90 }}>
                          <div className="progress">
                            <i style={{ width: `${Math.round(job.progress * 100)}%` }} />
                          </div>
                        </td>
                        <td className="tiny dim">{job.backend}</td>
                        <td className="tiny dim">{new Date(job.created_at).toLocaleString()}</td>
                        <td className="tiny dim">
                          {started && finished ? `${((finished - started) / 1000).toFixed(1)} s` : '—'}
                        </td>
                        <td className="right nowrap">
                          <button className="ghost sm" onClick={() => setInspect(job)}>
                            inspect
                          </button>
                          {job.status === 'pending' && (
                            <button
                              className="ghost sm"
                              onClick={async () => {
                                await api.cancelJob(job.id).catch(reportError)
                                void qc.invalidateQueries({ queryKey: ['jobs'] })
                              }}
                            >
                              cancel
                            </button>
                          )}
                          {(job.status === 'succeeded' || job.status === 'failed' || job.status === 'cancelled') && (
                            <button
                              className="ghost sm"
                              onClick={async () => {
                                await api.deleteJob(job.id).catch(reportError)
                                void qc.invalidateQueries({ queryKey: ['jobs'] })
                              }}
                            >
                              🗑
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {inspect && (
        <Modal title={`Job ${inspect.type}`} onClose={() => setInspect(null)} width={860}>
          <dl className="kv">
            <dt>id</dt>
            <dd className="mono tiny">{inspect.id}</dd>
            <dt>status</dt>
            <dd>{inspect.status}</dd>
            <dt>backend</dt>
            <dd>{inspect.backend}</dd>
          </dl>
          {inspect.error && (
            <pre className="tiny mono" style={{ color: 'var(--err)', whiteSpace: 'pre-wrap' }}>
              {inspect.error}
            </pre>
          )}
          <h4 className="small muted">Params</h4>
          <pre className="tiny mono" style={{ maxHeight: 180, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(truncateStrings(inspect.params), null, 2)}
          </pre>
          <h4 className="small muted">Result</h4>
          <pre className="tiny mono" style={{ maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
            {inspect.result ? JSON.stringify(truncateStrings(inspect.result), null, 2) : '—'}
          </pre>
        </Modal>
      )}
    </>
  )
}

/** Long sequences make the JSON preview unreadable — clip them. */
function truncateStrings(value: unknown, limit = 220): unknown {
  if (typeof value === 'string') return value.length > limit ? `${value.slice(0, limit)}… (${value.length} chars)` : value
  if (Array.isArray(value)) return value.slice(0, 40).map((v) => truncateStrings(v, limit))
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, truncateStrings(v, limit)]))
  }
  return value
}

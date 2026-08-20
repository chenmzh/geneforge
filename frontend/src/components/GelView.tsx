/** Virtual agarose gel rendering of digest fragment sizes. */
import type { Gel } from '@/api/types'

export default function GelView({ gel, height = 320 }: { gel: Gel; height?: number }) {
  return (
    <div>
      <div className="gel" style={{ overflowX: 'auto' }}>
        {gel.lanes.map((lane) => (
          <div key={lane.name}>
            <div className="lane" style={{ height }}>
              {lane.bands.map((band, i) => (
                <div
                  key={`${band.size}-${i}`}
                  className={`band${band.kind === 'ladder' ? ' ladder' : ''}`}
                  style={{ top: `${band.migration * 96}%`, opacity: 0.45 + band.intensity * 0.55 }}
                  title={`${band.size} bp`}
                >
                  <span>{band.size}</span>
                </div>
              ))}
            </div>
            <div className="lane-name">{lane.name}</div>
          </div>
        ))}
      </div>
      <p className="tiny dim" style={{ marginTop: 8 }}>
        Migration is a log-size approximation for {gel.gel_percent ?? 1}% agarose — use it to choose a gel, not to
        measure a band.
      </p>
    </div>
  )
}

/** Small shared UI primitives: modal, toasts, spinner, confirm. */
import { useEffect, type ReactNode } from 'react'
import { useUi } from '@/store/auth'

export function Modal({
  title,
  children,
  onClose,
  footer,
  width,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  footer?: ReactNode
  width?: number
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={width ? { width: `min(${width}px, 100%)` } : undefined}>
        <header>
          <span>{title}</span>
          <span style={{ flex: 1 }} />
          <button className="ghost icon" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  )
}

export function Toasts() {
  const { toasts, dismiss } = useUi()
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismiss(t.id)}>
          {t.message}
        </div>
      ))}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row small muted">
      <span className="spinner" /> {label ?? 'Working…'}
    </span>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <span className="k">{label}</span>
      <span className="v">{value}</span>
    </div>
  )
}

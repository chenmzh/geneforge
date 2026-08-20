/** Auth + UI stores (zustand). Tokens live in localStorage via the api client. */
import { create } from 'zustand'
import { api, loadTokens, saveTokens } from '@/api/client'
import type { Capabilities, User } from '@/api/types'

interface AuthState {
  user: User | null
  capabilities: Capabilities | null
  status: 'idle' | 'loading' | 'ready' | 'anonymous'
  error: string | null
  bootstrap: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  register: (payload: { email: string; username: string; password: string; full_name?: string }) => Promise<void>
  logout: () => void
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  capabilities: null,
  status: 'idle',
  error: null,

  bootstrap: async () => {
    set({ status: 'loading', error: null })
    const caps = await api.capabilities().catch(() => null)
    if (!loadTokens()?.access) {
      set({ status: 'anonymous', capabilities: caps, user: null })
      return
    }
    try {
      const user = await api.me()
      set({ user, capabilities: caps, status: 'ready' })
    } catch {
      saveTokens(null)
      set({ status: 'anonymous', user: null, capabilities: caps })
    }
  },

  login: async (username, password) => {
    set({ error: null })
    const token = await api.login(username, password)
    saveTokens({ access: token.access_token, refresh: token.refresh_token })
    const user = await api.me()
    set({ user, status: 'ready' })
  },

  register: async (payload) => {
    await api.register(payload)
    const token = await api.login(payload.username, payload.password)
    saveTokens({ access: token.access_token, refresh: token.refresh_token })
    const user = await api.me()
    set({ user, status: 'ready' })
  },

  logout: () => {
    saveTokens(null)
    set({ user: null, status: 'anonymous' })
  },
}))

export interface Toast { id: number; message: string; kind: 'info' | 'success' | 'error' }

interface UiState {
  toasts: Toast[]
  notify: (message: string, kind?: Toast['kind']) => void
  dismiss: (id: number) => void
}

let toastId = 1

export const useUi = create<UiState>((set) => ({
  toasts: [],
  notify: (message, kind = 'info') => {
    const id = toastId++
    set((state) => ({ toasts: [...state.toasts, { id, message, kind }] }))
    setTimeout(() => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })), kind === 'error' ? 7000 : 3800)
  },
  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}))

export function reportError(error: unknown, fallback = 'Request failed') {
  const message = error instanceof Error ? error.message : fallback
  useUi.getState().notify(message, 'error')
}

import type { Generation, SynthesisSettings, Utterance, Voice } from '../types'

const BASE = '/api/v1'

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, init)
  if (!r.ok) {
    let code = 'HTTP_ERROR'
    let message = r.statusText
    try {
      const body = await r.json()
      if (body?.error) {
        code = body.error.code ?? code
        message = body.error.message ?? message
      }
    } catch { /* non-json error */ }
    throw new ApiError(r.status, code, message)
  }
  return r.json() as Promise<T>
}

export const api = {
  voices: (params?: Record<string, string>) =>
    req<{ voices: Voice[] }>(
      '/voices' + (params ? '?' + new URLSearchParams(params) : '')),

  voice: (id: string) => req<Voice>(`/voices/${encodeURIComponent(id)}`),

  previewUrl: (id: string) => `${BASE}/voices/${encodeURIComponent(id)}/preview`,

  patchVoice: (id: string, patch: { name?: string; is_favorite?: boolean }) =>
    req(`/voices/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),

  analyze: (text: string, voice_id?: string) =>
    req<{ sentences: Utterance[] }>('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id }),
    }),

  synthesizeUtterances: async (
    utterances: Utterance[],
    voice_id: string,
    settings: SynthesisSettings,
    format: 'wav' | 'mp3' = 'wav',
  ): Promise<Blob> => {
    const r = await fetch(`${BASE}/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ utterances, voice_id, settings, format }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => null)
      throw new ApiError(r.status, body?.error?.code ?? 'HTTP_ERROR',
        body?.error?.message ?? r.statusText)
    }
    return r.blob()
  },

  createDictEntry: (entry: {
    surface: string; reading: string; accent_type?: number | null; pos?: string
  }) =>
    req('/dictionary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    }),

  synthesizeBlob: async (
    text: string,
    voice_id: string,
    settings: SynthesisSettings,
    format: 'wav' | 'mp3' = 'wav',
  ): Promise<Blob> => {
    const r = await fetch(`${BASE}/synthesize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, voice_id, settings, format }),
    })
    if (!r.ok) {
      const body = await r.json().catch(() => null)
      throw new ApiError(r.status, body?.error?.code ?? 'HTTP_ERROR',
        body?.error?.message ?? r.statusText)
    }
    return r.blob()
  },

  history: () => req<{ generations: Generation[] }>('/history'),

  health: () => req<{
    status: string
    engines: Record<string, { status: string; detail: string }>
    gpu: { name: string | null }
    device: string
  }>('/health'),
}

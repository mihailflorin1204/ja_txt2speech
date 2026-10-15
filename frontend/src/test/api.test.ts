import { describe, expect, it, vi, beforeEach } from 'vitest'
import { api, ApiError } from '../api/client'

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('parses voice list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ voices: [{ id: 'voicevox:1', engine: 'voicevox', name: 'ずんだもん' }] }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    )))
    const { voices } = await api.voices()
    expect(voices[0].id).toBe('voicevox:1')
  })

  it('throws ApiError with spec error envelope', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'LONG_TEXT', message: 'too long' } }),
      { status: 422 },
    )))
    await expect(api.synthesizeBlob('x', 'v:1', {} as never, 'wav'))
      .rejects.toMatchObject({ code: 'LONG_TEXT', status: 422 })
    expect(ApiError).toBeDefined()
  })
})

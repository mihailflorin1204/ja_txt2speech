import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAppStore } from '../store'
import type { SynthesisSettings } from '../types'

const BASE = '/api/v1'

interface Preset {
  id: number
  name: string
  voice_id: string
  settings: SynthesisSettings
}

export default function PresetMenu() {
  const [open, setOpen] = useState(false)
  const { voiceId, settings, setVoiceId, setSettings } = useAppStore()
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['presets'],
    queryFn: async () => {
      const r = await fetch(`${BASE}/presets`)
      return (await r.json()) as { presets: Preset[] }
    },
    enabled: open,
  })

  const save = useMutation({
    mutationFn: async (name: string) => {
      await fetch(`${BASE}/presets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, voice_id: voiceId, settings }),
      })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['presets'] }),
  })

  const del = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${BASE}/presets/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['presets'] }),
  })

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-3 py-1.5 rounded bg-slate-800 border border-slate-700 text-sm hover:bg-slate-700"
      >
        Presets ▾
      </button>
      {open && (
        <div className="absolute top-9 left-0 z-30 w-64 bg-slate-900 border border-slate-700 rounded-lg shadow-xl p-2">
          {(data?.presets ?? []).map((p) => (
            <div key={p.id} className="flex items-center gap-1 px-1 py-1 hover:bg-slate-800 rounded">
              <button
                className="flex-1 text-left text-sm truncate"
                onClick={() => { setVoiceId(p.voice_id); setSettings(p.settings); setOpen(false) }}
              >
                {p.name}
              </button>
              <button onClick={() => del.mutate(p.id)} className="text-slate-500 hover:text-red-400 text-xs">✕</button>
            </div>
          ))}
          <button
            className="w-full text-left text-sm text-indigo-400 hover:bg-slate-800 rounded px-1 py-1 mt-1"
            onClick={() => {
              const name = window.prompt('Preset name?')
              if (name) save.mutate(name)
            }}
          >
            + Save current…
          </button>
        </div>
      )}
    </div>
  )
}

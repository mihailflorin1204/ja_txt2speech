import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import type { Voice } from '../types'

export default function Voices() {
  const [engine, setEngine] = useState('')
  const [cloned, setCloned] = useState('')
  const qc = useQueryClient()

  const params: Record<string, string> = {}
  if (engine) params.engine = engine
  if (cloned) params.cloned = cloned

  const { data } = useQuery({
    queryKey: ['voices', engine, cloned],
    queryFn: () => api.voices(params),
  })

  const fav = useMutation({
    mutationFn: ({ id, fav }: { id: string; fav: boolean }) =>
      api.patchVoice(id, { is_favorite: fav }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['voices'] }),
  })

  const voices = data?.voices ?? []
  const engines = [...new Set(voices.map((v) => v.engine))]

  return (
    <div className="p-4">
      <div className="flex gap-3 mb-4 items-center">
        <select
          value={engine}
          onChange={(e) => setEngine(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm"
        >
          <option value="">All engines</option>
          {engines.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
        <select
          value={cloned}
          onChange={(e) => setCloned(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm"
        >
          <option value="">All voices</option>
          <option value="false">Built-in</option>
          <option value="true">Cloned by me</option>
        </select>
        <span className="text-sm text-slate-500">{voices.length} voices</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {voices.map((v) => (
          <VoiceCard key={v.id} voice={v} onFav={(f) => fav.mutate({ id: v.id, fav: f })} />
        ))}
      </div>
    </div>
  )
}

function VoiceCard({ voice, onFav }: { voice: Voice; onFav: (f: boolean) => void }) {
  return (
    <div className={`border rounded-lg p-3 ${voice.available ? 'border-slate-700 bg-slate-900' : 'border-slate-800 bg-slate-900/50 opacity-60'}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="font-medium">{voice.name}</div>
          <div className="text-xs text-slate-500">
            {voice.engine} · {voice.gender}
            {voice.is_cloned && ' · cloned'}
          </div>
        </div>
        <button
          onClick={() => onFav(!voice.is_favorite)}
          className={`text-lg ${voice.is_favorite ? 'text-yellow-400' : 'text-slate-600 hover:text-yellow-400'}`}
          title="Favorite"
        >
          ★
        </button>
      </div>
      {voice.styles.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {voice.styles.slice(0, 8).map((s) => (
            <span key={s} className="text-xs bg-slate-800 rounded px-1.5 py-0.5">{s}</span>
          ))}
        </div>
      )}
      <div className="flex items-center justify-between mt-3">
        {voice.available ? (
          <audio controls preload="none" src={api.previewUrl(voice.id)} className="h-8 w-44" />
        ) : (
          <span className="text-xs text-red-400">engine offline</span>
        )}
        {voice.credit && (
          <span className="text-xs text-slate-500 truncate ml-2" title={voice.credit}>
            {voice.credit}
          </span>
        )}
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../store'

export default function VoicePicker() {
  const { voiceId, setVoiceId } = useAppStore()
  const { data } = useQuery({ queryKey: ['voices'], queryFn: () => api.voices() })

  const voices = data?.voices ?? []

  return (
    <select
      value={voiceId ?? ''}
      onChange={(e) => setVoiceId(e.target.value)}
      className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm min-w-56"
    >
      <option value="" disabled>
        Select voice…
      </option>
      {voices.map((v) => (
        <option key={v.id} value={v.id} disabled={!v.available}>
          {v.is_favorite ? '★ ' : ''}
          {v.name} [{v.engine}]{!v.available ? ' (offline)' : ''}
        </option>
      ))}
    </select>
  )
}

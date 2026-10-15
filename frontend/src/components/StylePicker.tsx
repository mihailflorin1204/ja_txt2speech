import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAppStore } from '../store'

export default function StylePicker() {
  const { voiceId, settings, setSettings } = useAppStore()
  const { data: voice } = useQuery({
    queryKey: ['voice', voiceId],
    queryFn: () => api.voice(voiceId!),
    enabled: !!voiceId,
  })

  const styles = voice?.styles ?? []
  const hasStyle = styles.length > 0 && (voice?.features ?? []).includes('style')

  return (
    <div className="flex items-center gap-2">
      <select
        value={settings.style ?? ''}
        onChange={(e) => setSettings({ style: e.target.value || null })}
        disabled={!hasStyle}
        title={hasStyle ? 'Voice style' : 'This voice has no styles'}
        className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm disabled:opacity-40"
      >
        {!hasStyle && <option value="">no styles</option>}
        {styles.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <input
        type="range"
        min={0}
        max={1}
        step={0.05}
        value={settings.style_intensity}
        onChange={(e) => setSettings({ style_intensity: parseFloat(e.target.value) })}
        disabled={!hasStyle}
        title="Style intensity"
        className="w-24 accent-indigo-500 disabled:opacity-40"
      />
      <span className="text-xs text-slate-500 w-10">
        {Math.round(settings.style_intensity * 100)}%
      </span>
    </div>
  )
}

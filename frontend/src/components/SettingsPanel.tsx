import { useAppStore } from '../store'

const SLIDERS = [
  { key: 'speed', label: 'Speed', min: 0.5, max: 2.0, step: 0.05 },
  { key: 'pitch', label: 'Pitch', min: -12, max: 12, step: 1 },
  { key: 'volume', label: 'Volume', min: 0, max: 2.0, step: 0.05 },
  { key: 'intonation', label: 'Intonation', min: 0, max: 2.0, step: 0.05 },
  { key: 'pause_scale', label: 'Pause', min: 0, max: 3.0, step: 0.1 },
] as const

export default function SettingsPanel() {
  const { settings, setSettings } = useAppStore()

  return (
    <div className="space-y-4">
      {SLIDERS.map((s) => (
        <div key={s.key}>
          <div className="flex justify-between text-xs text-slate-400 mb-1">
            <span>{s.label}</span>
            <span>{settings[s.key].toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={s.min}
            max={s.max}
            step={s.step}
            value={settings[s.key]}
            onChange={(e) => setSettings({ [s.key]: parseFloat(e.target.value) })}
            className="w-full accent-indigo-500"
          />
        </div>
      ))}
    </div>
  )
}

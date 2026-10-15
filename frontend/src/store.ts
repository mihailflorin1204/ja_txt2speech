import { create } from 'zustand'
import { defaultSettings, type SynthesisSettings } from './types'

interface AppState {
  voiceId: string | null
  settings: SynthesisSettings
  setVoiceId: (id: string) => void
  setSettings: (s: Partial<SynthesisSettings>) => void
}

export const useAppStore = create<AppState>((set) => ({
  voiceId: null,
  settings: defaultSettings,
  setVoiceId: (id) => set({ voiceId: id }),
  setSettings: (s) => set((st) => ({ settings: { ...st.settings, ...s } })),
}))

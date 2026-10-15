export interface Voice {
  id: string
  engine: string
  engine_voice_id: string
  name: string
  gender: string
  styles: string[]
  features: string[]
  credit: string
  is_cloned: boolean
  is_favorite: boolean
  available: boolean
}

export interface SynthesisSettings {
  speed: number
  pitch: number
  volume: number
  intonation: number
  pause_scale: number
  style: string | null
  style_intensity: number
}

export const defaultSettings: SynthesisSettings = {
  speed: 1.0,
  pitch: 0,
  volume: 1.0,
  intonation: 1.0,
  pause_scale: 1.0,
  style: null,
  style_intensity: 1.0,
}

export interface Mora {
  text: string
  kana: string
  consonant: string | null
  vowel: string
  pitch: number
}

export interface AccentPhrase {
  moras: Mora[]
  accent: number
  pause_after_ms: number
  is_interrogative: boolean
}

export interface Utterance {
  text: string
  accent_phrases: AccentPhrase[]
  settings?: SynthesisSettings | null
}

export interface Generation {
  id: number
  text: string
  voice_id: string
  settings: SynthesisSettings
  format: string
  duration_s: number | null
  audio_url: string
  created_at: string
}

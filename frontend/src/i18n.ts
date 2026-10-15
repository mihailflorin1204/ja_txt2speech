/** Minimal i18n (spec M6): ja/en dictionary + language persisted to localStorage. */

import { useSyncExternalStore } from 'react'

export type Lang = 'ja' | 'en'

const dict = {
  ja: {
    nav_editor: 'エディタ', nav_voices: 'ボイス', nav_clone: 'クローン',
    nav_jobs: 'ジョブ', nav_dict: '辞書', nav_settings: '設定',
    generate: '生成', stream: 'ストリーム', stop: '停止',
    download: 'ダウンロード', history: '履歴', presets: 'プリセット',
    placeholder: '日本語のテキストを入力… (Ctrl+Enter で生成)',
    too_long: '{max} 文字を超えています。長文は Jobs ページで長文合成ジョブを作成してください。',
    err_long_text: 'テキストが長すぎます。長文ジョブを作成してください。',
    consent: 'この音声サンプルは私自身の声、または権利者の許可を得た音声であることを確認します。',
    surface_ph: 'surface (表層形)',
    reading_ph: 'reading (カタカナ)',
  },
  en: {
    nav_editor: 'Editor', nav_voices: 'Voices', nav_clone: 'Clone',
    nav_jobs: 'Jobs', nav_dict: 'Dictionary', nav_settings: 'Settings',
    generate: 'Generate', stream: 'Stream', stop: 'Stop',
    download: 'Download', history: 'History', presets: 'Presets',
    placeholder: 'Enter Japanese text… (Ctrl+Enter to generate)',
    too_long: 'Over {max} characters — create a long-text job on the Jobs page instead.',
    err_long_text: 'Text is too long. Create a long-text job.',
    consent: "I confirm I own this voice sample or have the owner's permission.",
    surface_ph: 'surface',
    reading_ph: 'reading (katakana)',
  },
} as const

export type Key = keyof (typeof dict)['ja']

let lang: Lang = (localStorage.getItem('jptts_lang') as Lang) || 'en'
const listeners = new Set<() => void>()

export function t(key: Key): string {
  return dict[lang][key] ?? dict.en[key] ?? key
}

export function getLang(): Lang {
  return lang
}

export function setLang(l: Lang): void {
  lang = l
  localStorage.setItem('jptts_lang', l)
  listeners.forEach((f) => f())
}

export function onLangChange(f: () => void): () => void {
  listeners.add(f)
  return () => listeners.delete(f)
}

/** Subscribe the calling component to language changes; returns `t`. */
export function useT(): typeof t {
  useSyncExternalStore(onLangChange, getLang)
  return t
}

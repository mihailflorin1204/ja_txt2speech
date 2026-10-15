/** Minimal i18n (spec M6): ja/en dictionary + language persisted to localStorage. */

export type Lang = 'ja' | 'en'

const dict = {
  ja: {
    nav_editor: 'エディタ', nav_voices: 'ボイス', nav_clone: 'クローン',
    nav_jobs: 'ジョブ', nav_dict: '辞書', nav_settings: '設定',
    generate: '生成', stream: 'ストリーム', stop: '停止',
    download: 'ダウンロード', history: '履歴', presets: 'プリセット',
    placeholder: '日本語のテキストを入力…',
  },
  en: {
    nav_editor: 'Editor', nav_voices: 'Voices', nav_clone: 'Clone',
    nav_jobs: 'Jobs', nav_dict: 'Dictionary', nav_settings: 'Settings',
    generate: 'Generate', stream: 'Stream', stop: 'Stop',
    download: 'Download', history: 'History', presets: 'Presets',
    placeholder: 'Enter Japanese text…',
  },
} as const

export type Key = keyof (typeof dict)['ja']

let lang: Lang = (localStorage.getItem('jptts_lang') as Lang) || 'ja'
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

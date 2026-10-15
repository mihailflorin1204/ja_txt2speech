import { useSyncExternalStore } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api/client'
import { getLang, onLangChange, setLang, t, type Key } from './i18n'
import Editor from './pages/Editor'
import Voices from './pages/Voices'
import Clone from './pages/Clone'
import Jobs from './pages/Jobs'
import Dictionary from './pages/Dictionary'
import Settings from './pages/Settings'

const nav: { to: string; key: Key; end?: boolean }[] = [
  { to: '/', key: 'nav_editor', end: true },
  { to: '/voices', key: 'nav_voices' },
  { to: '/clone', key: 'nav_clone' },
  { to: '/jobs', key: 'nav_jobs' },
  { to: '/dictionary', key: 'nav_dict' },
  { to: '/settings', key: 'nav_settings' },
]

export default function App() {
  const health = useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: 15000 })
  const lang = useSyncExternalStore(onLangChange, getLang)

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col">
      <header className="border-b border-slate-800 px-4 py-2 flex items-center gap-6">
        <span className="font-bold text-lg">jp-tts</span>
        <nav className="flex gap-1">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded text-sm ${
                  isActive ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-white'
                }`
              }
            >
              {t(n.key)}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3">
          <button
            onClick={() => setLang(lang === 'ja' ? 'en' : 'ja')}
            className="text-xs text-slate-400 hover:text-white border border-slate-700 rounded px-2 py-0.5"
            aria-label="Switch language"
          >
            {lang === 'ja' ? 'EN' : '日本語'}
          </button>
          <span className="text-xs text-slate-500">
            {health.data ? `${health.data.device}${health.data.gpu?.name ? ' · ' + health.data.gpu.name : ''}` : 'connecting…'}
          </span>
        </div>
      </header>
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<Editor />} />
          <Route path="/voices" element={<Voices />} />
          <Route path="/clone" element={<Clone />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/dictionary" element={<Dictionary />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}

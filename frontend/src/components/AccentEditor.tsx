import { useState } from 'react'
import type { AccentPhrase, SynthesisSettings, Utterance } from '../types'

/** Tokyo pitch pattern: mora 1 is L unless nucleus==1; high through nucleus, then drop. */
function pitchPattern(phrase: AccentPhrase): ('H' | 'L')[] {
  const n = phrase.moras.length
  const acc = phrase.accent
  return phrase.moras.map((_, i) => {
    if (acc === 1) return i === 0 ? 'H' : 'L'
    if (acc === 0 || acc >= n) return i === 0 ? 'L' : 'H'
    return i === 0 ? 'L' : i < acc ? 'H' : 'L'
  })
}

function PitchLine({ phrase }: { phrase: AccentPhrase }) {
  const pat = pitchPattern(phrase)
  const w = Math.max(phrase.moras.length * 16, 24)
  const pts = pat.map((p, i) => `${i * 16 + 8},${p === 'H' ? 4 : 14}`).join(' ')
  return (
    <svg width={w} height={18} className="block">
      <polyline points={pts} fill="none" stroke="#818cf8" strokeWidth="1.5" />
      {pat.map((p, i) => (
        <circle key={i} cx={i * 16 + 8} cy={p === 'H' ? 4 : 14} r={2}
          fill={i + 1 === phrase.accent ? '#f59e0b' : '#818cf8'} />
      ))}
    </svg>
  )
}

interface Props {
  utterances: Utterance[]
  onChange: (utts: Utterance[]) => void
  onSaveDict: (surface: string, reading: string, accent: number) => void
}

export default function AccentEditor({ utterances, onChange, onSaveDict }: Props) {
  const [editing, setEditing] = useState<{ s: number; p: number } | null>(null)
  const [editReading, setEditReading] = useState('')
  const [furigana, setFurigana] = useState(false)
  const [overrideOpen, setOverrideOpen] = useState<number | null>(null)

  const clone = (): Utterance[] => JSON.parse(JSON.stringify(utterances))

  const update = (fn: (u: Utterance[]) => void) => {
    const next = clone()
    fn(next)
    onChange(next)
  }

  const setAccent = (s: number, p: number, moraIdx: number) =>
    update((u) => { u[s].accent_phrases[p].accent = moraIdx + 1 })

  const splitPhrase = (s: number, p: number, atMora: number) =>
    update((u) => {
      const ph = u[s].accent_phrases[p]
      if (atMora <= 0 || atMora >= ph.moras.length) return
      const a: AccentPhrase = { ...ph, moras: ph.moras.slice(0, atMora), pause_after_ms: 0 }
      const b: AccentPhrase = {
        ...ph,
        moras: ph.moras.slice(atMora),
        accent: ph.accent > atMora ? ph.accent - atMora : 0,
      }
      a.accent = Math.min(ph.accent, a.moras.length)
      ;u[s].accent_phrases.splice(p, 1, a, b)
    })

  const mergePhrase = (s: number, p: number) =>
    update((u) => {
      const phrases = u[s].accent_phrases
      if (p + 1 >= phrases.length) return
      const a = phrases[p]
      const b = phrases[p + 1]
      a.moras = [...a.moras, ...b.moras]
      if (b.accent > 0) a.accent = a.moras.length - b.moras.length + b.accent
      a.pause_after_ms = b.pause_after_ms
      phrases.splice(p + 1, 1)
    })

  const setPause = (s: number, p: number) =>
    update((u) => {
      const ph = u[s].accent_phrases[p]
      ph.pause_after_ms = ph.pause_after_ms >= 500 ? 0 : 500
    })

  const applyReading = (s: number, p: number) => {
    if (!editReading.trim()) { setEditing(null); return }
    update((u) => {
      const ph = u[s].accent_phrases[p]
      const surf = ph.moras[0]?.text ?? ''
      const small = 'ャュョァィゥェォヮ'
      const moras = []
      const kana = editReading.trim().toUpperCase()
      for (let i = 0; i < kana.length; i++) {
        let k = kana[i]
        if (i + 1 < kana.length && small.includes(kana[i + 1])) k += kana[++i]
        moras.push({ text: surf, kana: k, consonant: null, vowel: '', pitch: 0 })
      }
      ph.moras = moras
      ph.accent = Math.min(ph.accent, moras.length)
    })
    setEditing(null)
  }

  return (
    <div className="space-y-6">
      <label className="text-xs text-slate-400 flex items-center gap-1.5">
        <input type="checkbox" checked={furigana}
          onChange={(e) => setFurigana(e.target.checked)}
          className="accent-indigo-500" />
        Furigana preview
      </label>
      {utterances.map((utt, s) => (
        <div key={s} className="border border-slate-800 rounded-lg p-3">
          {furigana && (
            <div className="text-lg mb-2 leading-8">
              {utt.accent_phrases.map((ph, p) => (
                <ruby key={p}>
                  {ph.moras[0]?.text}
                  <rt className="text-xs text-indigo-300">
                    {ph.moras.map((m) => m.kana).join('')}
                  </rt>
                </ruby>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-end gap-y-3">
            {utt.accent_phrases.map((ph, p) => {
              const reading = ph.moras.map((m) => m.kana).join('')
              const surface = ph.moras[0]?.text ?? ''
              return (
                <div key={p} className="flex items-end">
                  <div className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 mx-0.5">
                    {/* katakana reading (click to edit) */}
                    {editing?.s === s && editing?.p === p ? (
                      <input
                        autoFocus
                        value={editReading}
                        onChange={(e) => setEditReading(e.target.value)}
                        onBlur={() => applyReading(s, p)}
                        onKeyDown={(e) => e.key === 'Enter' && applyReading(s, p)}
                        className="bg-slate-900 border border-indigo-500 rounded px-1 text-xs w-28 mb-0.5 block"
                      />
                    ) : (
                      <button
                        className="text-xs text-indigo-300 block mb-0.5 hover:text-indigo-200"
                        title="edit reading"
                        onClick={() => { setEditing({ s, p }); setEditReading(reading) }}
                      >
                        {reading}
                      </button>
                    )}
                    <PitchLine phrase={ph} />
                    {/* mora row: click a mora to set accent nucleus */}
                    <div className="flex mt-0.5 justify-center">
                      {ph.moras.map((m, mi) => (
                        <button
                          key={mi}
                          onClick={() => setAccent(s, p, mi)}
                          title={`accent nucleus → mora ${mi + 1}`}
                          className={`w-4 text-center text-sm ${
                            mi + 1 === ph.accent ? 'text-amber-400 font-bold' : 'hover:text-indigo-300'
                          }`}
                        >
                          {m.kana}
                        </button>
                      ))}
                    </div>
                    <div className="text-xs text-slate-300 text-center">
                      {surface} <span className="text-slate-500">@{ph.accent}</span>
                    </div>
                    <div className="flex gap-1 justify-center mt-1 text-[10px]">
                      {ph.moras.length > 1 && (
                        <button onClick={() => splitPhrase(s, p, Math.max(1, ph.accent || Math.ceil(ph.moras.length / 2)))}
                          className="text-slate-400 hover:text-white" title="split phrase">✂</button>
                      )}
                      <button onClick={() => mergePhrase(s, p)}
                        className="text-slate-400 hover:text-white" title="merge with next">⇄</button>
                      <button
                        onClick={() => onSaveDict(surface, reading, ph.accent)}
                        className="text-slate-400 hover:text-white" title="save to dictionary">💾</button>
                    </div>
                  </div>
                  {/* pause handle between chips */}
                  <button
                    onClick={() => setPause(s, p)}
                    className={`text-[10px] px-0.5 mb-1 ${ph.pause_after_ms ? 'text-amber-400' : 'text-slate-600 hover:text-slate-400'}`}
                    title="toggle pause"
                  >
                    {ph.pause_after_ms ? `⏸${ph.pause_after_ms}ms` : '+'}
                  </button>
                </div>
              )
            })}
          </div>
          {/* per-sentence override */}
          <div className="mt-2">
            <button
              onClick={() => setOverrideOpen(overrideOpen === s ? null : s)}
              className="text-[10px] text-slate-500 hover:text-slate-300"
              title="per-sentence settings override"
            >
              ⚙ sentence settings{utt.settings ? ' •' : ''}
            </button>
            {overrideOpen === s && (
              <div className="flex gap-4 mt-1.5 text-xs items-center flex-wrap">
                {(['speed', 'pitch'] as const).map((k) => (
                  <label key={k} className="flex items-center gap-1.5">
                    <span className="text-slate-400">{k}</span>
                    <input
                      type="range"
                      min={k === 'speed' ? 0.5 : -12}
                      max={k === 'speed' ? 2 : 12}
                      step={k === 'speed' ? 0.05 : 1}
                      value={utt.settings?.[k] ?? (k === 'speed' ? 1 : 0)}
                      onChange={(e) => update((u) => {
                        const cur: Partial<SynthesisSettings> = { ...(u[s].settings ?? {}) }
                        cur[k] = parseFloat(e.target.value)
                        u[s].settings = cur as SynthesisSettings
                      })}
                      className="w-20 accent-indigo-500"
                    />
                    <span className="w-8 text-slate-500">
                      {(utt.settings?.[k] ?? (k === 'speed' ? 1 : 0)).toString()}
                    </span>
                  </label>
                ))}
                <button
                  onClick={() => update((u) => { u[s].settings = null })}
                  className="text-slate-500 hover:text-white"
                >clear</button>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

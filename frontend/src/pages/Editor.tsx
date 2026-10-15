import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../api/client'
import { useAppStore } from '../store'
import { StreamPlayer } from '../audio/player'
import VoicePicker from '../components/VoicePicker'
import StylePicker from '../components/StylePicker'
import SettingsPanel from '../components/SettingsPanel'
import HistoryDrawer from '../components/HistoryDrawer'
import AccentEditor from '../components/AccentEditor'
import PresetMenu from '../components/PresetMenu'
import { useT } from '../i18n'
import type { Utterance } from '../types'

const MAX_CHARS = 500

export default function Editor() {
  const [text, setText] = useState('')
  const [format, setFormat] = useState<'wav' | 'mp3'>('wav')
  const [audioUrl, setAudioUrl] = useState<string | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const [activeSentence, setActiveSentence] = useState(-1)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [mode, setMode] = useState<'text' | 'accent'>('text')
  const [utterances, setUtterances] = useState<Utterance[] | null>(null)
  const { voiceId, settings } = useAppStore()
  const t = useT()
  const audioRef = useRef<HTMLAudioElement>(null)
  const playerRef = useRef<StreamPlayer | null>(null)
  const qc = useQueryClient()

  useEffect(() => {
    playerRef.current = new StreamPlayer()
    return () => playerRef.current?.stop()
  }, [])

  const synth = useMutation({
    mutationFn: () => (utterances && mode === 'accent'
      ? api.synthesizeUtterances(utterances, voiceId!, settings, format)
      : api.synthesizeBlob(text, voiceId!, settings, format)),
    onSuccess: (blob) => {
      if (audioUrl) URL.revokeObjectURL(audioUrl)
      const url = URL.createObjectURL(blob)
      setAudioUrl(url)
      requestAnimationFrame(() => audioRef.current?.play())
    },
  })

  const tooLong = text.length > MAX_CHARS
  const hasInput = !!voiceId && text.trim().length > 0 && !tooLong
  const canGenerate = hasInput && !synth.isPending && !streaming

  const generate = () => {
    if (canGenerate) synth.mutate()
  }

  const streamToggle = () => {
    const player = playerRef.current
    if (!player) return
    if (streaming) {
      player.stop()
      setStreaming(false)
      setActiveSentence(-1)
      return
    }
    if (!hasInput) return
    setStreamError(null)
    setStreaming(true)
    setActiveSentence(-1)
    void player.start(text, voiceId!, settings, {
      onSentence: (i) => setActiveSentence(i),
      onDone: () => { setStreaming(false); setActiveSentence(-1) },
      onError: (_c, m) => {
        setStreamError(m)
        setStreaming(false)
        setActiveSentence(-1)
      },
    })
  }

  const analyze = async () => {
    const res = await api.analyze(text)
    setUtterances(res.sentences)
    setMode('accent')
  }

  const saveToDict = async (surface: string, reading: string, accent: number) => {
    await api.createDictEntry({ surface, reading, accent_type: accent })
    qc.invalidateQueries({ queryKey: ['dict'] })
  }

  const download = () => {
    if (!audioUrl) return
    const a = document.createElement('a')
    a.href = audioUrl
    a.download = `jp-tts.${format}`
    a.click()
  }

  // sentence segments for highlight (same boundary chars as backend splitter)
  const segments = streaming || activeSentence >= 0
    ? text.split(/(?<=[。！？!?…\n])/).filter(Boolean)
    : []

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col p-4 gap-3">
        <div className="flex items-center gap-3 flex-wrap">
          <VoicePicker />
          <StylePicker />
          <PresetMenu />
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as 'wav' | 'mp3')}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm"
          >
            <option value="wav">WAV</option>
            <option value="mp3">MP3</option>
          </select>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex rounded overflow-hidden border border-slate-700 text-xs">
              <button
                onClick={() => setMode('text')}
                className={`px-3 py-1.5 ${mode === 'text' ? 'bg-indigo-600' : 'bg-slate-800 text-slate-400'}`}
              >Text</button>
              <button
                onClick={() => (utterances ? setMode('accent') : analyze())}
                disabled={!text.trim()}
                title="Ctrl+Shift+A"
                className={`px-3 py-1.5 ${mode === 'accent' ? 'bg-indigo-600' : 'bg-slate-800 text-slate-400'}`}
              >Accent</button>
            </div>
            <span className={`text-xs ${tooLong ? 'text-red-400' : 'text-slate-500'}`}>
              {text.length} / {MAX_CHARS}
            </span>
          </div>
        </div>

        <div className="flex-1 relative overflow-auto">
          {mode === 'accent' && utterances ? (
            <div className="absolute inset-0 bg-slate-900 border border-slate-700 rounded p-3 overflow-auto">
              <AccentEditor
                utterances={utterances}
                onChange={setUtterances}
                onSaveDict={saveToDict}
              />
              <button
                onClick={() => setMode('text')}
                className="mt-2 text-xs text-slate-400 hover:text-white"
              >← back to text</button>
            </div>
          ) : (
            <>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) generate()
                  if (e.key === 'A' && e.ctrlKey && e.shiftKey) { e.preventDefault(); void analyze() }
                }}
                aria-label="Text to synthesize"
                placeholder={t('placeholder')}
                className="absolute inset-0 bg-slate-900 border border-slate-700 rounded p-3 text-lg resize-none focus:outline-none focus:border-indigo-500"
              />
              {segments.length > 0 && (
                <div className="absolute inset-0 bg-slate-900/95 border border-indigo-700 rounded p-3 text-lg overflow-auto pointer-events-none">
                  {segments.map((s, i) => (
                    <span
                      key={i}
                      className={i === activeSentence
                        ? 'bg-indigo-600/50 rounded'
                        : ''}
                    >
                      {s}
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {tooLong && (
          <div className="text-sm text-amber-400 bg-amber-950/40 border border-amber-800 rounded p-2">
            {t('too_long').replace('{max}', String(MAX_CHARS))}
          </div>
        )}
        {(synth.isError || streamError) && (
          <div className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded p-2">
            {streamError ??
              ((synth.error as ApiError).code === 'LONG_TEXT'
                ? t('err_long_text')
                : (synth.error as Error).message)}
          </div>
        )}

        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={generate}
            disabled={!canGenerate}
            aria-label="Generate audio (Ctrl+Enter)"
            className="px-5 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 font-medium"
          >
            {synth.isPending ? 'Generating…' : 'Generate (Ctrl+Enter)'}
          </button>
          <button
            onClick={streamToggle}
            disabled={!hasInput && !streaming}
            aria-label={streaming ? 'Stop streaming' : 'Stream audio'}
            aria-pressed={streaming}
            className={`px-4 py-2 rounded font-medium ${
              streaming
                ? 'bg-red-600 hover:bg-red-500'
                : 'bg-slate-800 hover:bg-slate-700 disabled:bg-slate-800 disabled:text-slate-600'
            }`}
          >
            {streaming ? 'Stop' : 'Stream'}
          </button>
          <button
            onClick={download}
            disabled={!audioUrl}
            aria-label={`Download audio as ${format}`}
            className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 disabled:text-slate-600"
          >
            Download {format.toUpperCase()}
          </button>
          <button
            onClick={() => setHistoryOpen(true)}
            aria-label="Open generation history"
            aria-expanded={historyOpen}
            className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700"
          >
            History
          </button>
          {audioUrl && <audio ref={audioRef} controls src={audioUrl} className="flex-1 h-9" aria-label="Generated audio" />}
        </div>
      </div>

      <aside className="w-64 border-l border-slate-800 p-4">
        <h3 className="text-sm font-semibold text-slate-400 mb-3">Voice settings</h3>
        <SettingsPanel />
      </aside>

      <HistoryDrawer open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  )
}

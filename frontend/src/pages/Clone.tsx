import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../i18n'

const BASE = '/api/v1'

interface Quality {
  duration_s: number
  sample_rate: number
  silence_pct: number
  clipping_pct: number
  ok: boolean
  issues: string[]
}

interface Sample {
  id: string
  name: string
  audio_path: string
  transcript: string
  duration_s: number
  status: string
  quality: Quality | null
  created_at: string
}

export default function Clone() {
  const qc = useQueryClient()
  const t = useT()
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [transcript, setTranscript] = useState('')
  const [consent, setConsent] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [lastResult, setLastResult] = useState<{ status: string; quality: Quality } | null>(null)

  const { data } = useQuery({
    queryKey: ['samples'],
    queryFn: async () => (await (await fetch(`${BASE}/clone/samples`)).json()) as { samples: Sample[] },
  })

  const upload = useMutation({
    mutationFn: async () => {
      const fd = new FormData()
      fd.append('file', file!)
      fd.append('name', name || 'My clone')
      fd.append('transcript', transcript)
      fd.append('consent', String(consent))
      const r = await fetch(`${BASE}/clone/samples`, { method: 'POST', body: fd })
      if (!r.ok) {
        const b = await r.json().catch(() => null)
        throw new Error(b?.error?.message ?? r.statusText)
      }
      return r.json() as Promise<{ id: string; voice_id: string; status: string; quality: Quality }>
    },
    onSuccess: (d) => {
      setLastResult(d)
      setFile(null)
      qc.invalidateQueries({ queryKey: ['samples'] })
    },
  })

  const transcribe = useMutation({
    mutationFn: async (id: string) => {
      const r = await fetch(`${BASE}/clone/samples/${id}/transcribe`, { method: 'POST' })
      if (!r.ok) throw new Error((await r.json())?.error?.message ?? r.statusText)
      return r.json()
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['samples'] }),
  })

  const del = useMutation({
    mutationFn: async (id: string) => {
      await fetch(`${BASE}/clone/samples/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['samples'] }),
  })

  return (
    <div className="p-6 max-w-3xl">
      <h2 className="text-xl font-semibold mb-2">Voice Cloning</h2>
      <p className="text-sm text-slate-400 mb-4">
        Upload a 3–30 s clean Japanese speech sample. Everything stays local.
      </p>

      <section className="border border-slate-800 rounded-lg p-4 mb-6">
        <div className="grid gap-3">
          <input value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Voice name"
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm" />
          <button onClick={() => fileRef.current?.click()}
            className="px-3 py-2 rounded bg-slate-800 hover:bg-slate-700 text-sm text-left">
            {file ? `📎 ${file.name}` : 'Choose audio file… (wav/mp3)'}
          </button>
          <input ref={fileRef} type="file" accept="audio/*" className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <textarea value={transcript} onChange={(e) => setTranscript(e.target.value)}
            placeholder="Transcript of the sample (optional — improves cloning). Japanese text."
            className="bg-slate-900 border border-slate-700 rounded p-2 text-sm h-16 resize-y" />
          <label className="text-xs text-amber-300 flex gap-2 items-start">
            <input type="checkbox" checked={consent}
              onChange={(e) => setConsent(e.target.checked)} className="mt-0.5 accent-indigo-500" />
            <span>{t('consent')}</span>
          </label>
          <button onClick={() => upload.mutate()}
            disabled={!file || !consent || upload.isPending}
            className="px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 text-sm disabled:bg-slate-700 disabled:text-slate-500">
            {upload.isPending ? 'Checking quality…' : 'Upload & quality-check'}
          </button>
        </div>
        {upload.isError && (
          <p className="text-red-400 text-sm mt-2">{(upload.error as Error).message}</p>
        )}
        {lastResult && (
          <div className={`mt-3 text-sm rounded p-3 border ${
            lastResult.status === 'ready'
              ? 'bg-green-950/40 border-green-800 text-green-300'
              : 'bg-red-950/40 border-red-800 text-red-300'}`}>
            {lastResult.status === 'ready' ? '✓ Sample accepted' : '✗ Sample rejected'}
            <ul className="text-xs mt-1 text-slate-300">
              <li>{lastResult.quality.duration_s}s · {lastResult.quality.sample_rate} Hz · silence {lastResult.quality.silence_pct}%</li>
              {lastResult.quality.issues.map((i, k) => <li key={k}>• {i}</li>)}
            </ul>
          </div>
        )}
      </section>

      <h3 className="font-medium mb-2">Your samples</h3>
      <div className="space-y-2">
        {(data?.samples ?? []).map((s) => (
          <div key={s.id} className="border border-slate-800 rounded-lg p-3 flex items-center gap-3">
            <div className="flex-1">
              <div className="font-medium text-sm">{s.name}
                <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${
                  s.status === 'ready' ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'}`}>
                  {s.status}
                </span>
              </div>
              <div className="text-xs text-slate-500">
                {s.duration_s}s · gptsovits:{s.id}
                {s.transcript && ` · “${s.transcript.slice(0, 40)}${s.transcript.length > 40 ? '…' : ''}”`}
              </div>
            </div>
            <audio controls src={`${BASE}/clone/samples/${s.id}/audio`} className="h-8 w-48" />
            {!s.transcript && (
              <button onClick={() => transcribe.mutate(s.id)}
                className="text-xs text-indigo-400 hover:underline">transcribe</button>
            )}
            <button onClick={() => del.mutate(s.id)}
              className="text-xs text-red-400 hover:underline">delete</button>
          </div>
        ))}
        {!data?.samples?.length && <p className="text-slate-500 text-sm">No samples yet.</p>}
      </div>
    </div>
  )
}

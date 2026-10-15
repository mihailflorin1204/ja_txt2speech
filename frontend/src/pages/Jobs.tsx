import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAppStore } from '../store'

const BASE = '/api/v1'

interface Job {
  id: string
  kind: string
  status: string
  voice_id: string | null
  progress: { done: number; total: number }
  error: string | null
  eta_seconds?: number | null
  failed_sentences?: { id: number; text: string; attempts: number }[]
}

interface Chapter {
  title: string
  text: string
  chars?: number
}

export default function Jobs() {
  const { voiceId } = useAppStore()
  const qc = useQueryClient()
  const [text, setText] = useState('')
  const [chapters, setChapters] = useState<Chapter[] | null>(null)
  const [format, setFormat] = useState('mp3')
  const [mode, setMode] = useState('per_chapter')
  const [m4b, setM4b] = useState(true)
  const [srt, setSrt] = useState(true)
  const fileRef = useRef<HTMLInputElement>(null)

  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: async () => (await (await fetch(`${BASE}/jobs`)).json()) as { jobs: Job[] },
    refetchInterval: 2000,
  })

  const preview = useMutation({
    mutationFn: async (): Promise<{ chapters: Chapter[]; total_sentences: number }> => {
      const r = await fetch(`${BASE}/jobs/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice_id: voiceId ?? 'x' }),
      })
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    },
    onSuccess: (d) => setChapters(d.chapters.map((c) => ({ title: c.title, text: c.text }))),
  })

  const create = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${BASE}/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: chapters ? undefined : text,
          chapters: chapters ?? undefined,
          voice_id: voiceId,
          export_options: { format, mode, m4b, srt },
        }),
      })
      if (!r.ok) throw new Error((await r.json())?.error?.message ?? r.statusText)
      return r.json()
    },
    onSuccess: () => {
      setText('')
      setChapters(null)
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const act = async (id: string, action: string) => {
    await fetch(`${BASE}/jobs/${id}/${action}`, { method: 'POST' })
    qc.invalidateQueries({ queryKey: ['jobs'] })
  }

  const uploadFile = async (f: File) => {
    const fd = new FormData()
    fd.append('file', f)
    fd.append('voice_id', voiceId ?? '')
    fd.append('export_options', JSON.stringify({ format, mode, m4b, srt }))
    const r = await fetch(`${BASE}/jobs`, { method: 'POST', body: fd })
    if (!r.ok) throw new Error((await r.json())?.error?.message ?? r.statusText)
    qc.invalidateQueries({ queryKey: ['jobs'] })
  }

  return (
    <div className="p-6 max-w-5xl">
      <h2 className="text-xl font-semibold mb-4">Long-text Jobs</h2>

      <section className="border border-slate-800 rounded-lg p-4 mb-6">
        <h3 className="font-medium mb-2">New job</h3>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Paste long text (up to 1,000,000 chars) or upload .txt / .epub / .md"
          className="w-full h-32 bg-slate-900 border border-slate-700 rounded p-3 text-sm resize-y"
        />
        <div className="flex items-center gap-3 mt-3 flex-wrap">
          <button onClick={() => fileRef.current?.click()}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-sm">
            Upload file…
          </button>
          <input ref={fileRef} type="file" accept=".txt,.epub,.md" className="hidden"
            onChange={(e) => e.target.files?.[0] && uploadFile(e.target.files[0])} />
          <select value={format} onChange={(e) => setFormat(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm">
            <option value="mp3">MP3</option>
            <option value="wav">WAV</option>
          </select>
          <select value={mode} onChange={(e) => setMode(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm">
            <option value="per_chapter">per chapter</option>
            <option value="combined">combined</option>
          </select>
          <label className="text-sm flex items-center gap-1">
            <input type="checkbox" checked={m4b} onChange={(e) => setM4b(e.target.checked)} className="accent-indigo-500" /> M4B
          </label>
          <label className="text-sm flex items-center gap-1">
            <input type="checkbox" checked={srt} onChange={(e) => setSrt(e.target.checked)} className="accent-indigo-500" /> SRT
          </label>
          <button onClick={() => preview.mutate()} disabled={!text.trim() || preview.isPending}
            className="px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-sm disabled:text-slate-500">
            Preview splits
          </button>
          <button onClick={() => create.mutate()} disabled={!voiceId || (!text.trim() && !chapters)}
            className="px-4 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-sm disabled:bg-slate-700 disabled:text-slate-500">
            Create job
          </button>
        </div>
        {chapters && (
          <div className="mt-3 text-sm">
            <p className="text-slate-400 mb-1">{chapters.length} chapters detected (review titles, edit before creating):</p>
            {chapters.map((c, i) => (
              <input key={i} value={c.title}
                onChange={(e) => {
                  const next = [...chapters]; next[i] = { ...c, title: e.target.value }; setChapters(next)
                }}
                className="block w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-sm mb-1" />
            ))}
          </div>
        )}
        {create.isError && <p className="text-red-400 text-sm mt-2">{(create.error as Error).message}</p>}
      </section>

      <div className="space-y-3">
        {(jobs.data?.jobs ?? []).map((j) => (
          <JobRow key={j.id} job={j} onAct={act} />
        ))}
        {!jobs.data?.jobs?.length && <p className="text-slate-500 text-sm">No jobs yet.</p>}
      </div>
    </div>
  )
}

function JobRow({ job, onAct }: { job: Job; onAct: (id: string, a: string) => void }) {
  const pct = job.progress.total ? Math.round(100 * job.progress.done / job.progress.total) : 0
  const { data: outputs } = useQuery({
    queryKey: ['job-outputs', job.id],
    queryFn: async () =>
      (await (await fetch(`${BASE}/jobs/${job.id}/outputs`)).json()) as
        { outputs: { name: string; url: string; size: number }[] },
    enabled: job.status === 'completed',
  })
  const { data: detail } = useQuery({
    queryKey: ['job', job.id],
    queryFn: async () => (await (await fetch(`${BASE}/jobs/${job.id}`)).json()) as Job,
    refetchInterval: job.status === 'running' ? 2000 : false,
  })
  const eta = detail?.eta_seconds
  const failed = detail?.failed_sentences ?? []

  return (
    <div className="border border-slate-800 rounded-lg p-3">
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono text-slate-500">{job.id.slice(0, 8)}</span>
        <span className={`text-xs px-2 py-0.5 rounded ${
          job.status === 'completed' ? 'bg-green-900 text-green-300'
          : job.status === 'failed' ? 'bg-red-900 text-red-300'
          : job.status === 'running' ? 'bg-indigo-900 text-indigo-300'
          : 'bg-slate-800 text-slate-400'}`}>{job.status}</span>
        <div className="flex-1 h-1.5 bg-slate-800 rounded overflow-hidden">
          <div className="h-full bg-indigo-500" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs text-slate-400 w-24 text-right">
          {job.progress.done}/{job.progress.total}{eta ? ` · ~${eta}s` : ''}
        </span>
      </div>
      <div className="flex gap-2 mt-2 text-xs">
        {job.status === 'running' && (
          <button onClick={() => onAct(job.id, 'pause')} className="text-amber-400 hover:underline">pause</button>
        )}
        {(job.status === 'paused') && (
          <button onClick={() => onAct(job.id, 'resume')} className="text-indigo-400 hover:underline">resume</button>
        )}
        {['running', 'paused', 'queued'].includes(job.status) && (
          <button onClick={() => onAct(job.id, 'cancel')} className="text-red-400 hover:underline">cancel</button>
        )}
        {failed.length > 0 && (
          <button onClick={() => onAct(job.id, 'retry')} className="text-amber-400 hover:underline">
            retry {failed.length} failed
          </button>
        )}
      </div>
      {failed.length > 0 && (
        <div className="mt-2 text-xs text-red-400">
          Failed sentences: {failed.map((f) => <div key={f.id} className="truncate">{f.text}</div>)}
        </div>
      )}
      {outputs?.outputs && outputs.outputs.length > 0 && (
        <div className="mt-2 flex gap-3 text-xs">
          {outputs.outputs.map((o) => (
            <a key={o.name} href={o.url} download
              className="text-indigo-400 hover:underline">{o.name}</a>
          ))}
        </div>
      )}
      {job.error && <p className="text-xs text-red-400 mt-1">{job.error}</p>}
    </div>
  )
}

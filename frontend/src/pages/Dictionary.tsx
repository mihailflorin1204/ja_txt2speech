import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useT } from '../i18n'

const BASE = '/api/v1'

interface Entry {
  id: number
  surface: string
  reading: string
  accent_type: number | null
  pos: string
  priority: number
}

export default function Dictionary() {
  const [q, setQ] = useState('')
  const [form, setForm] = useState({ surface: '', reading: '', accent_type: '', pos: '', priority: '0' })
  const qc = useQueryClient()
  const t = useT()

  const { data } = useQuery({
    queryKey: ['dict', q],
    queryFn: async () => {
      const r = await fetch(`${BASE}/dictionary?q=${encodeURIComponent(q)}`)
      return (await r.json()) as { entries: Entry[]; total: number }
    },
  })

  const create = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${BASE}/dictionary`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          surface: form.surface,
          reading: form.reading,
          accent_type: form.accent_type === '' ? null : parseInt(form.accent_type),
          pos: form.pos,
          priority: parseInt(form.priority) || 0,
        }),
      })
      if (!r.ok) throw new Error(await r.text())
    },
    onSuccess: () => {
      setForm({ surface: '', reading: '', accent_type: '', pos: '', priority: '0' })
      qc.invalidateQueries({ queryKey: ['dict'] })
    },
  })

  const del = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${BASE}/dictionary/${id}`, { method: 'DELETE' })
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dict'] }),
  })

  const importFile = async (file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    await fetch(`${BASE}/dictionary/import`, { method: 'POST', body: fd })
    qc.invalidateQueries({ queryKey: ['dict'] })
  }

  return (
    <div className="p-6 max-w-4xl">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-xl font-semibold">User Dictionary</h2>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="search…"
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm flex-1 max-w-xs"
        />
        <a href={`${BASE}/dictionary/export?format=csv`} className="text-sm text-indigo-400 hover:underline">Export CSV</a>
        <a href={`${BASE}/dictionary/export?format=json`} className="text-sm text-indigo-400 hover:underline">JSON</a>
        <label className="text-sm text-indigo-400 hover:underline cursor-pointer">
          Import
          <input type="file" accept=".csv,.json" className="hidden"
            onChange={(e) => e.target.files?.[0] && importFile(e.target.files[0])} />
        </label>
      </div>

      <div className="flex gap-2 mb-4 flex-wrap">
        <input placeholder={t('surface_ph')} value={form.surface}
          onChange={(e) => setForm({ ...form, surface: e.target.value })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm" />
        <input placeholder={t('reading_ph')} value={form.reading}
          onChange={(e) => setForm({ ...form, reading: e.target.value })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm" />
        <input placeholder="accent" value={form.accent_type}
          onChange={(e) => setForm({ ...form, accent_type: e.target.value.replace(/\D/g, '') })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm w-20" />
        <input placeholder="pos" value={form.pos}
          onChange={(e) => setForm({ ...form, pos: e.target.value })}
          className="bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-sm w-28" />
        <button
          onClick={() => create.mutate()}
          disabled={!form.surface || !form.reading}
          className="px-4 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 text-sm"
        >Add</button>
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-400 border-b border-slate-800">
            <th className="py-2">Surface</th><th>Reading</th><th>Accent</th>
            <th>POS</th><th>Priority</th><th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.entries ?? []).map((e) => (
            <tr key={e.id} className="border-b border-slate-800/50">
              <td className="py-2">{e.surface}</td>
              <td>{e.reading}</td>
              <td>{e.accent_type ?? ''}</td>
              <td className="text-slate-400">{e.pos}</td>
              <td className="text-slate-400">{e.priority}</td>
              <td>
                <button onClick={() => del.mutate(e.id)}
                  className="text-red-400 hover:text-red-300 text-xs">delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {(data?.entries.length ?? 0) === 0 && (
        <p className="text-slate-500 text-sm mt-4">No entries yet.</p>
      )}
    </div>
  )
}

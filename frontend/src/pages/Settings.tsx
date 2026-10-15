import { useQuery } from '@tanstack/react-query'

const BASE = '/api/v1'

interface Health {
  status: string
  engines: Record<string, { status: string; detail: string }>
  gpu: { name: string | null; memory_used_mb: number | null;
         memory_total_mb: number | null; utilization_pct: number | null }
  device: string
}

interface Metrics {
  uptime_s: number
  total_synths: number
  total_errors: number
  rtf_median: number | null
  latency_median_ms: number | null
  queue_length: number
  engines: Record<string, string>
  gpu: Health['gpu']
  recent_errors: { ts: number; code: string; detail: string }[]
  per_engine: Record<string, { count: number; rtf_median: number | null }>
}

export default function Settings() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await (await fetch(`${BASE}/health`)).json()) as Health,
    refetchInterval: 5000,
  })
  const metrics = useQuery({
    queryKey: ['metrics'],
    queryFn: async () => (await (await fetch(`${BASE}/metrics`)).json()) as Metrics,
    refetchInterval: 5000,
  })

  const h = health.data
  const m = metrics.data

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <h2 className="text-xl font-semibold">Settings & Status</h2>

      <section className="border border-slate-800 rounded-lg p-4">
        <h3 className="font-medium mb-2">Engines</h3>
        {h ? Object.entries(h.engines).map(([k, e]) => (
          <div key={k} className="flex items-center gap-3 text-sm py-1">
            <span className={`w-2 h-2 rounded-full ${e.status === 'online' ? 'bg-green-400' : 'bg-slate-600'}`} />
            <span className="w-28">{k}</span>
            <span className="text-slate-400">{e.status}{e.detail ? ` — ${e.detail}` : ''}</span>
          </div>
        )) : <p className="text-slate-500 text-sm">loading…</p>}
      </section>

      <section className="border border-slate-800 rounded-lg p-4">
        <h3 className="font-medium mb-2">GPU</h3>
        {h?.gpu?.name ? (
          <div className="text-sm text-slate-300">
            {h.gpu.name} — {h.gpu.memory_used_mb} / {h.gpu.memory_total_mb} MB
            ({h.gpu.utilization_pct}% util)
          </div>
        ) : <p className="text-slate-500 text-sm">No GPU detected — CPU mode</p>}
      </section>

      <section className="border border-slate-800 rounded-lg p-4">
        <h3 className="font-medium mb-2">Metrics</h3>
        {m ? (
          <div className="text-sm text-slate-300 space-y-1">
            <div>uptime {Math.round(m.uptime_s)}s · {m.total_synths} synths · {m.total_errors} errors · queue {m.queue_length}</div>
            {m.rtf_median != null && <div>median RTF: {m.rtf_median} · median latency: {m.latency_median_ms} ms</div>}
            {Object.entries(m.per_engine).map(([k, v]) => (
              <div key={k} className="text-xs text-slate-400">{k}: {v.count} synths{v.rtf_median != null ? `, RTF ${v.rtf_median}` : ''}</div>
            ))}
            {m.recent_errors.length > 0 && (
              <div className="mt-2">
                <div className="text-xs text-slate-500">recent errors:</div>
                {m.recent_errors.slice(-5).map((e, i) => (
                  <div key={i} className="text-xs text-red-400 font-mono">{e.code}: {e.detail}</div>
                ))}
              </div>
            )}
          </div>
        ) : <p className="text-slate-500 text-sm">loading…</p>}
      </section>
    </div>
  )
}

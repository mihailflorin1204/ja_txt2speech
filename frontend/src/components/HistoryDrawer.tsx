import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function HistoryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data } = useQuery({
    queryKey: ['history'],
    queryFn: api.history,
    enabled: open,
  })

  if (!open) return null
  return (
    <div className="fixed inset-y-0 right-0 w-96 bg-slate-900 border-l border-slate-700 shadow-xl p-4 overflow-auto z-20">
      <div className="flex justify-between items-center mb-3">
        <h2 className="font-semibold">History</h2>
        <button onClick={onClose} className="text-slate-400 hover:text-white">✕</button>
      </div>
      <div className="space-y-3">
        {(data?.generations ?? []).map((g) => (
          <div key={g.id} className="border border-slate-800 rounded p-2">
            <div className="text-sm truncate">{g.text}</div>
            <div className="text-xs text-slate-500 mt-1">
              {g.voice_id} · {g.duration_s?.toFixed(1)}s
            </div>
            <audio controls src={g.audio_url} className="w-full h-8 mt-1" />
          </div>
        ))}
        {!data?.generations?.length && (
          <p className="text-slate-500 text-sm">No generations yet.</p>
        )}
      </div>
    </div>
  )
}

/**
 * WebSocket streaming player (spec §5.3).
 *
 * Opens /api/v1/stream, sends `start`, receives a `format` message then
 * per-sentence `sentence` messages + binary PCM frames, then `done`.
 * PCM frames are fed to an AudioWorklet for gapless playback.
 */

import type { SynthesisSettings } from '../types'

export interface StreamCallbacks {
  onSentence?: (index: number, text: string) => void
  onDone?: () => void
  onError?: (code: string, message: string) => void
}

export class StreamPlayer {
  private ws: WebSocket | null = null
  private ctx: AudioContext | null = null
  private node: AudioWorkletNode | null = null
  playing = false

  async start(
    text: string,
    voiceId: string,
    settings: SynthesisSettings,
    cb: StreamCallbacks = {},
  ): Promise<void> {
    this.stop()
    this.playing = true

    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/stream`)
    this.ws = ws
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'start', text, voice_id: voiceId, settings }))
    }

    ws.onmessage = async (ev) => {
      if (typeof ev.data === 'string') {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'format') {
          await this.initAudio(msg.sample_rate)
        } else if (msg.type === 'done' || msg.type === 'stopped') {
          this.node?.port.postMessage({ type: 'done' })
        } else if (msg.type === 'error') {
          cb.onError?.(msg.code, msg.message)
          this.stop()
        }
        return
      }
      // binary frame: 4-byte LE index + s16le pcm
      const buf = ev.data as ArrayBuffer
      const index = new DataView(buf).getUint32(0, true)
      const pcm = new Int16Array(buf, 4)
      const f32 = new Float32Array(pcm.length)
      for (let i = 0; i < pcm.length; i++) f32[i] = pcm[i] / 32768
      this.node?.port.postMessage(
        { type: 'push', index, samples: f32 }, [f32.buffer])
    }

    ws.onerror = () => cb.onError?.('WS_ERROR', 'websocket error')
    ws.onclose = () => {
      // closing is handled by 'done'/'ended' paths
    }

    this._cb = cb
  }

  private _cb: StreamCallbacks = {}

  private async initAudio(sampleRate: number): Promise<void> {
    this.ctx = new AudioContext({ sampleRate })
    await this.ctx.audioWorklet.addModule('/pcm-player-worklet.js')
    this.node = new AudioWorkletNode(this.ctx, 'pcm-player')
    this.node.port.onmessage = (e) => {
      const m = e.data
      if (m.type === 'sentence-start') {
        this._cb.onSentence?.(m.index, '')
      } else if (m.type === 'ended') {
        this.playing = false
        this._cb.onDone?.()
        this.cleanup()
      }
    }
    this.node.connect(this.ctx.destination)
  }

  stop(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'stop' }))
    }
    this.node?.port.postMessage({ type: 'stop' })
    this.playing = false
    this.cleanup()
  }

  private cleanup(): void {
    this.ws?.close()
    this.ws = null
    this.node?.disconnect()
    this.node = null
    this.ctx?.close().catch(() => undefined)
    this.ctx = null
  }
}

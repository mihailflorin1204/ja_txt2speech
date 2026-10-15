// AudioWorkletProcessor that plays pushed Float32 PCM chunks gaplessly.
// Messages in:  {type:'push', index:number, samples:Float32Array}
//               {type:'done'}  {type:'stop'}
// Messages out: {type:'sentence-start', index:number}  {type:'ended'}
class PcmPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.queue = []
    this.offset = 0
    this.done = false
    this.stopped = false
    this.currentIndex = -1
    this.port.onmessage = (e) => {
      const m = e.data
      if (m.type === 'push') this.queue.push(m)
      else if (m.type === 'done') this.done = true
      else if (m.type === 'stop') { this.stopped = true; this.queue.length = 0 }
    }
  }

  process(inputs, outputs) {
    const out = outputs[0][0]
    let written = 0
    while (written < out.length && this.queue.length > 0) {
      const head = this.queue[0]
      if (head.index !== this.currentIndex) {
        this.currentIndex = head.index
        this.port.postMessage({ type: 'sentence-start', index: head.index })
      }
      const n = Math.min(out.length - written, head.samples.length - this.offset)
      out.set(head.samples.subarray(this.offset, this.offset + n), written)
      this.offset += n
      written += n
      if (this.offset >= head.samples.length) {
        this.queue.shift()
        this.offset = 0
      }
    }
    // underrun fills with silence; done+empty => end playback
    if (this.stopped || (this.done && this.queue.length === 0)) {
      this.port.postMessage({ type: 'ended' })
      return false
    }
    return true
  }
}

registerProcessor('pcm-player', PcmPlayerProcessor)

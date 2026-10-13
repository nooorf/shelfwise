// Microphone capture for voice input: 16 kHz mono 16-bit PCM in 32 ms
// frames, the format the server's VAD and Whisper take. The AudioContext runs at 16 kHz, so
// the browser resamples; a small AudioWorklet turns floats into Int16 frames off the main
// thread. Echo cancellation keeps the assistant's own voice out of the microphone.

export const FRAME = 512 // samples: 32 ms at 16 kHz

const WORKLET = `
class Pcm16 extends AudioWorkletProcessor {
  constructor() { super(); this.frame = new Int16Array(${FRAME}); this.n = 0 }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0]
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        const v = Math.max(-1, Math.min(1, channel[i]))
        this.frame[this.n++] = v < 0 ? v * 32768 : v * 32767
        if (this.n === ${FRAME}) {
          this.port.postMessage(this.frame.buffer, [this.frame.buffer])
          this.frame = new Int16Array(${FRAME})
          this.n = 0
        }
      }
    }
    return true
  }
}
registerProcessor('pcm16', Pcm16)
`

export class Microphone {
  private context: AudioContext | null = null
  private stream: MediaStream | null = null

  get open(): boolean {
    return this.context !== null
  }

  /** Asks for the microphone (the browser prompts once) and streams frames to `onFrame`. */
  async start(onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    if (this.context) return
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    const context = new AudioContext({ sampleRate: 16_000 })
    this.context = context
    const url = URL.createObjectURL(new Blob([WORKLET], { type: 'text/javascript' }))
    try {
      await context.audioWorklet.addModule(url)
    } finally {
      URL.revokeObjectURL(url)
    }
    const worklet = new AudioWorkletNode(context, 'pcm16')
    worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => onFrame(event.data)
    context.createMediaStreamSource(this.stream).connect(worklet)
  }

  stop(): void {
    this.stream?.getTracks().forEach((track) => track.stop())
    void this.context?.close()
    this.stream = null
    this.context = null
  }
}

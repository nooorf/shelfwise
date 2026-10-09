// Plays the reply's sentences as they arrive (design doc §21): each WAV clip is decoded in
// order and scheduled right after the previous one, so speech is gapless while later
// sentences are still being made. stop() is barge-in: silence now, and late clips from the
// interrupted turns are dropped. Browsers only allow sound after a user gesture: unlock() is
// called from clicks and key presses.

export interface AudioOutput {
  readonly currentTime: number
  resume(): Promise<void>
  decodeAudioData(data: ArrayBuffer): Promise<AudioBuffer>
  createBufferSource(): AudioBufferSourceNode
  createAnalyser?(): AnalyserNode
  readonly destination: AudioNode
  readonly sampleRate?: number
}

const LEAD_S = 0.02 // scheduling slack so the first clip doesn't start in the past

export class SpeechPlayer {
  private output: AudioOutput | null = null
  private tap: AnalyserNode | null = null // what the avatar's lip-sync reads
  private sources: AudioBufferSourceNode[] = []
  private endsAt = 0
  private latestTurn = 0
  private stoppedThrough = 0 // clips for turns up to here are not played
  private chain: Promise<void> = Promise.resolve()
  private readonly onPlaying: (playing: boolean) => void
  private readonly makeOutput: () => AudioOutput

  constructor(onPlaying: (playing: boolean) => void, makeOutput: () => AudioOutput = () => new AudioContext()) {
    this.onPlaying = onPlaying
    this.makeOutput = makeOutput
  }

  /** From a user gesture: create or wake the audio output. */
  unlock(): void {
    this.output ??= this.makeOutput()
    void this.output.resume()
  }

  /** The analyser every clip plays through (null before unlock or without Web Audio). */
  get analyser(): AnalyserNode | null {
    return this.tap
  }

  get sampleRate(): number {
    return this.output?.sampleRate ?? 48_000
  }

  /** A turn the server answered: stop() covers it even before its audio arrives. */
  seen(turn: number): void {
    this.latestTurn = Math.max(this.latestTurn, turn)
  }

  play(turn: number, wavBase64: string): Promise<void> {
    this.seen(turn)
    this.chain = this.chain.then(() => this.schedule(turn, wavBase64)).catch(() => {})
    return this.chain
  }

  stop(): void {
    this.stoppedThrough = this.latestTurn
    for (const source of this.sources) {
      source.onended = null
      source.stop()
    }
    const wasPlaying = this.sources.length > 0
    this.sources = []
    this.endsAt = 0
    if (wasPlaying) this.onPlaying(false)
  }

  private through(output: AudioOutput): AudioNode {
    if (!this.tap && output.createAnalyser) {
      this.tap = output.createAnalyser()
      this.tap.fftSize = 2048
      this.tap.smoothingTimeConstant = 0.3
      this.tap.connect(output.destination)
    }
    return this.tap ?? output.destination
  }

  private async schedule(turn: number, wavBase64: string): Promise<void> {
    const output = this.output
    if (!output || turn <= this.stoppedThrough) return
    const bytes = Uint8Array.from(atob(wavBase64), (c) => c.charCodeAt(0))
    const buffer = await output.decodeAudioData(bytes.buffer)
    if (turn <= this.stoppedThrough) return // stopped while decoding
    const source = output.createBufferSource()
    source.buffer = buffer
    source.connect(this.through(output))
    const start = Math.max(output.currentTime + LEAD_S, this.endsAt)
    source.start(start)
    this.endsAt = start + buffer.duration
    source.onended = () => {
      this.sources = this.sources.filter((s) => s !== source)
      if (this.sources.length === 0) this.onPlaying(false)
    }
    if (this.sources.push(source) === 1) this.onPlaying(true)
  }
}

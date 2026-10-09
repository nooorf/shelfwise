import { describe, expect, it, vi } from 'vitest'

import type { AudioOutput } from './player'
import { SpeechPlayer } from './player'

function fakeOutput() {
  const started: { at: number; duration: number; stopped: boolean }[] = []
  const output: AudioOutput = {
    currentTime: 10,
    resume: () => Promise.resolve(),
    destination: {} as AudioNode,
    decodeAudioData: (data) => Promise.resolve({ duration: data.byteLength / 4 } as AudioBuffer),
    createBufferSource: () => {
      const entry = { at: 0, duration: 0, stopped: false }
      const node = {
        buffer: null as AudioBuffer | null,
        onended: null as (() => void) | null,
        connect: () => {},
        start(at: number) {
          entry.at = at
          entry.duration = this.buffer?.duration ?? 0
          started.push(entry)
        },
        stop() {
          entry.stopped = true
        },
      }
      return node as unknown as AudioBufferSourceNode
    },
  }
  return { output, started }
}

const clip = (bytes: number) => btoa('x'.repeat(bytes)) // decodes to `bytes / 4` seconds

describe('speech player', () => {
  it('plays sentences back to back in order', async () => {
    const { output, started } = fakeOutput()
    const onPlaying = vi.fn()
    const player = new SpeechPlayer(onPlaying, () => output)
    player.unlock()

    void player.play(1, clip(8))
    await player.play(1, clip(4))

    expect(started.map((s) => [s.at, s.duration])).toEqual([[10.02, 2], [12.02, 1]])
    expect(onPlaying).toHaveBeenCalledWith(true)
  })

  it('stops now and drops late clips from interrupted turns', async () => {
    const { output, started } = fakeOutput()
    const onPlaying = vi.fn()
    const player = new SpeechPlayer(onPlaying, () => output)
    player.unlock()
    await player.play(1, clip(8))
    player.seen(2) // turn 2 answered, its audio not here yet

    player.stop()
    await player.play(2, clip(8)) // arrives after the barge-in
    await player.play(3, clip(4)) // the new question's answer

    expect(started.map((s) => s.stopped)).toEqual([true, false])
    expect(started[1].duration).toBe(1)
    expect(onPlaying).toHaveBeenLastCalledWith(true)
  })

  it('stays silent until a gesture unlocks audio', async () => {
    const { output, started } = fakeOutput()
    const player = new SpeechPlayer(() => {}, () => output)
    await player.play(1, clip(8))
    expect(started).toEqual([])
  })
})

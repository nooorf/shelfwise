// The talking avatar (design doc §21.4, Phase 6b): a VRM model in a small three.js scene,
// lazy-loaded so the app never waits for it. It follows the same states as the orb (idle,
// listening, thinking, speaking) and moves its mouth from the speech audio the speakers are
// playing (lipsync.ts), so sound and lips can't drift apart. When playback stops the mouth
// closes on that frame. Any failure (no WebGL, the file missing, too slow) hands back to the orb.
import { VRMUtils } from '@pixiv/three-vrm'
import type { VRM } from '@pixiv/three-vrm'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef, useState } from 'react'
import { Vector3 } from 'three'

import type { Status } from '../session/store'
import { bands, CLOSED, loudness, smooth, VISEMES, visemes } from './lipsync'
import { blinkAt, bone, loadVrm } from './load'
import type { Visemes } from './lipsync'

export type Fallback = 'load' | 'slow'

interface StageProps {
  url: string
  distance?: number // camera distance in metres: 1.15 head and shoulders, more shows more of her
  status: Status
  analyser: () => { node: AnalyserNode | null; sampleRate: number }
  onFallback: (why: Fallback) => void
  onReady: () => void
}

const MIN_FPS = 20 // averaged over the first SAMPLE_S seconds after loading
const SAMPLE_S = 3

function Model({ url, status, analyser, onFallback, onReady, distance = 1.15 }: StageProps) {
  const [vrm, setVrm] = useState<VRM | null>(null)
  const camera = useThree((s) => s.camera)
  const mouth = useRef<Visemes>({ ...CLOSED })
  const clock = useRef({ t: 0, nextBlink: 2, frames: 0, sampled: false })
  const buffers = useRef<{ freq: Uint8Array<ArrayBuffer>; time: Float32Array<ArrayBuffer> } | null>(null)

  useEffect(() => {
    let live = true
    loadVrm(url)
      .then((loaded) => {
        if (!live) return
        const head = new Vector3()
        bone(loaded, 'head')?.getWorldPosition(head)
        const drop = (distance - 1.15) * 0.14 // further back, aim a little lower: shoulders, then chest
        camera.position.set(0, head.y + 0.04 - drop, distance) // the head bone sits at the skull's
        camera.lookAt(0, head.y + 0.01 - drop, 0) // base: aim a little above it
        setVrm(loaded)
        onReady()
      })
      .catch(() => live && onFallback('load'))
    return () => {
      live = false
    }
  }, [url, camera, onFallback, onReady, distance])

  useEffect(
    () => () => {
      if (vrm) VRMUtils.deepDispose(vrm.scene) // free the GPU memory when the avatar goes
    },
    [vrm],
  )

  useFrame((_, dt) => {
    if (!vrm) return
    const c = clock.current
    c.t += dt
    c.frames += 1
    if (!c.sampled && c.t >= SAMPLE_S) {
      c.sampled = true
      if (c.frames / c.t < MIN_FPS) onFallback('slow')
    }
    const expressions = vrm.expressionManager

    // Breathing and a slow sway: alive even when idle.
    const chest = bone(vrm, 'chest') ?? bone(vrm, 'spine')
    if (chest) chest.rotation.x = Math.sin(c.t * 1.6) * 0.012
    const head = bone(vrm, 'head')
    if (head) {
      const thinking = status === 'searching' || status === 'writing'
      const target = {
        x: thinking ? -0.08 : status === 'listening' ? 0.04 : 0,
        y: (thinking ? 0.18 : 0) + Math.sin(c.t * 0.5) * 0.04,
        z: status === 'listening' ? 0.09 : Math.sin(c.t * 0.7) * 0.015,
      }
      const k = 1 - Math.exp(-dt / 0.25)
      head.rotation.x += (target.x - head.rotation.x) * k
      head.rotation.y += (target.y - head.rotation.y) * k
      head.rotation.z += (target.z - head.rotation.z) * k
    }

    const blink = blinkAt(c.t, c.nextBlink)
    c.nextBlink = blink.next
    expressions?.setValue('blink', blink.closed)

    // Mood: a slight smile at rest, attentive when listening.
    expressions?.setValue('happy', status === 'ready' ? 0.15 : 0)
    expressions?.setValue('relaxed', status === 'listening' ? 0.3 : 0)

    // Lip-sync from the playing audio; closed the frame speech stops (barge-in).
    const { node, sampleRate } = analyser()
    let target = CLOSED
    if (status === 'speaking' && node) {
      if (!buffers.current || buffers.current.freq.length !== node.frequencyBinCount) {
        buffers.current = {
          freq: new Uint8Array(node.frequencyBinCount),
          time: new Float32Array(node.fftSize),
        }
      }
      node.getByteFrequencyData(buffers.current.freq)
      node.getFloatTimeDomainData(buffers.current.time)
      target = visemes(loudness(buffers.current.time), bands(buffers.current.freq, sampleRate))
      mouth.current = smooth(mouth.current, target, dt)
    } else {
      mouth.current = { ...CLOSED }
    }
    for (const v of VISEMES) expressions?.setValue(v, mouth.current[v])

    vrm.update(dt)
  })

  return vrm ? <primitive object={vrm.scene} /> : null
}

export default function AvatarStage(props: StageProps) {
  return (
    <Canvas
      camera={{ fov: 24, near: 0.1, far: 20, position: [0, 1.4, 0.85] }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      aria-hidden="true"
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[0.6, 1.8, 1.4]} intensity={0.9} />
      <directionalLight position={[-1.2, 1.4, -0.8]} intensity={0.6} color="#fff3b0" />
      <Model {...props} />
    </Canvas>
  )
}

// The talking avatar (design doc §21.4, Phase 6b): a VRM model in a small three.js scene,
// lazy-loaded so the app never waits for it. It follows the same states as the orb (idle,
// listening, thinking, speaking) and moves its mouth from the speech audio the speakers are
// playing (lipsync.ts), so sound and lips can't drift apart. When playback stops the mouth
// closes on that frame. Any failure (no WebGL, the file missing, too slow) hands back to the orb.
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm'
import type { VRM, VRMHumanBoneName } from '@pixiv/three-vrm'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useRef, useState } from 'react'
import { Vector3 } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

import type { Status } from '../session/store'
import { bands, CLOSED, loudness, smooth, VISEMES, visemes } from './lipsync'
import type { Visemes } from './lipsync'

export type Fallback = 'load' | 'slow'

interface StageProps {
  url: string
  status: Status
  analyser: () => { node: AnalyserNode | null; sampleRate: number }
  onFallback: (why: Fallback) => void
  onReady: () => void
}

const MIN_FPS = 20 // averaged over the first SAMPLE_S seconds after loading
const SAMPLE_S = 3

function bone(vrm: VRM, name: VRMHumanBoneName) {
  return vrm.humanoid.getNormalizedBoneNode(name)
}

function Model({ url, status, analyser, onFallback, onReady }: StageProps) {
  const [vrm, setVrm] = useState<VRM | null>(null)
  const camera = useThree((s) => s.camera)
  const mouth = useRef<Visemes>({ ...CLOSED })
  const clock = useRef({ t: 0, nextBlink: 2, frames: 0, sampled: false })
  const buffers = useRef<{ freq: Uint8Array<ArrayBuffer>; time: Float32Array<ArrayBuffer> } | null>(null)

  useEffect(() => {
    let live = true
    const loader = new GLTFLoader()
    loader.register((parser) => new VRMLoaderPlugin(parser))
    loader
      .loadAsync(url)
      .then((gltf) => {
        const loaded = gltf.userData.vrm as VRM | undefined
        if (!live || !loaded) return
        VRMUtils.removeUnnecessaryVertices(gltf.scene)
        VRMUtils.combineSkeletons(gltf.scene)
        VRMUtils.rotateVRM0(loaded) // VRM 0.x faces away; 1.0 already faces the camera
        bone(loaded, 'leftUpperArm')?.rotation.set(0, 0, -1.2) // out of the T-pose
        bone(loaded, 'rightUpperArm')?.rotation.set(0, 0, 1.2)
        bone(loaded, 'leftLowerArm')?.rotation.set(0, 0, -0.15)
        bone(loaded, 'rightLowerArm')?.rotation.set(0, 0, 0.15)
        loaded.update(0)
        const head = new Vector3()
        bone(loaded, 'head')?.getWorldPosition(head)
        camera.position.set(0, head.y + 0.04, 1.15) // the head bone sits at the skull's base:
        camera.lookAt(0, head.y + 0.01, 0) // aim a little above it for head and shoulders
        setVrm(loaded)
        onReady()
      })
      .catch(() => live && onFallback('load'))
    return () => {
      live = false
    }
  }, [url, camera, onFallback, onReady])

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

    // Blink every 2.5-6 s: the eyelids close and open over the last 150 ms before nextBlink.
    if (c.t >= c.nextBlink) c.nextBlink = c.t + 2.5 + Math.random() * 3.5
    const untilBlink = c.nextBlink - c.t
    const blink = untilBlink < 0.15 ? Math.sin((1 - untilBlink / 0.15) * Math.PI) : 0
    expressions?.setValue('blink', blink)

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
      <ambientLight intensity={0.8} />
      <directionalLight position={[0.6, 1.8, 1.4]} intensity={1.1} />
      <Model {...props} />
    </Canvas>
  )
}

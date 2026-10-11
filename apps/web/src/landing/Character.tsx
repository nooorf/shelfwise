// The landing page's character (lazy-loaded with three.js): the assistant's VRM model behind
// the far shelf of the book arc, head and shoulders over it. Once loaded it rises into view
// (gaze.ts `rise`), then browses the books, follows the cursor while it moves, and looks at
// whichever book is pointed at or focused, smiling a little more. Eyes jump to the target at
// once, the head and neck catch up, as people do. The canvas's bottom edge is the middle of
// the shelf, so the rest of the body is always out of sight.
import { VRMUtils } from '@pixiv/three-vrm'
import type { VRM } from '@pixiv/three-vrm'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { Group, Object3D, Plane, Raycaster, Vector2, Vector3 } from 'three'

import { aim, approach, gazeTarget, rise } from '../avatar/gaze'
import type { Point } from '../avatar/gaze'
import { blinkAt, bone, loadVrm } from '../avatar/load'

interface Props {
  url: string
  arc: RefObject<HTMLElement | null>
  pointed: RefObject<HTMLElement | null>
  onReady: () => void
  onFailed: () => void
}

const GAZE_Z = 0.5 // the plane the cursor is taken to be on: just in front of the face
// Framing, as fractions of the canvas height from the top: the top of the head, the chest.
const FRAME = { headTop: 0.36, chest: 0.97 } // room above for hair, and clear of the headline
const SHARE = { spine: 0.12, neck: 0.33, head: 0.55 }
const PEEK = { delay: 0.35, duration: 1.15 } // seconds after the model is ready
const SMILE = { book: 0.45, cursor: 0.22, browse: 0.1 }
const REFRESH_S = 0.5 // how often the books' positions on screen are read again

function seconds(): number {
  return performance.now() / 1000
}

function centre(el: Element): Point {
  const r = el.getBoundingClientRect()
  return { x: r.left + r.width / 2, y: r.top + r.height / 2 }
}

function Model({ url, arc, pointed, onReady, onFailed }: Props) {
  const [vrm, setVrm] = useState<VRM | null>(null)
  const { camera, gl, size } = useThree()
  const lift = useRef<Group>(null) // carries the peek, so the model itself stays where it loaded
  const cursor = useRef<(Point & { at: number }) | null>(null)
  const books = useRef<{ points: Point[]; at: number }>({ points: [], at: -1 })
  const state = useRef({
    yaw: 0, pitch: 0, smile: 0, t: 0, nextBlink: 2, ready: -1, drop: 0.5, // ready: when the framing was set
    head: new Vector3(),
  })
  const tools = useMemo(
    () => ({
      ray: new Raycaster(),
      ndc: new Vector2(),
      plane: new Plane(new Vector3(0, 0, 1), -GAZE_Z),
      hit: new Vector3(),
      local: new Vector3(),
      target: new Object3D(),
    }),
    [],
  )

  useEffect(() => {
    const move = (e: PointerEvent) => {
      cursor.current = { x: e.clientX, y: e.clientY, at: seconds() }
    }
    window.addEventListener('pointermove', move, { passive: true })
    return () => window.removeEventListener('pointermove', move)
  }, [])

  useEffect(() => {
    let live = true
    loadVrm(url)
      .then((loaded) => {
        if (!live) return
        loaded.scene.updateMatrixWorld(true)
        const head = new Vector3()
        bone(loaded, 'head')?.getWorldPosition(head)
        state.current.head = loaded.scene.worldToLocal(head.clone())
        if (loaded.lookAt) {
          loaded.lookAt.target = tools.target
          loaded.lookAt.autoUpdate = true
        }
        setVrm(loaded)
        onReady()
      })
      .catch(() => live && onFailed())
    return () => {
      live = false
    }
  }, [url, tools, onReady, onFailed])

  useEffect(
    () => () => {
      if (vrm) VRMUtils.deepDispose(vrm.scene)
    },
    [vrm],
  )

  // Fit head and shoulders to the canvas, whatever the model's size; the peek starts once
  // the framing is known.
  useEffect(() => {
    if (!vrm || !('fov' in camera)) return
    const s = state.current
    const chest = new Vector3()
    ;(bone(vrm, 'upperChest') ?? bone(vrm, 'chest') ?? bone(vrm, 'spine'))?.getWorldPosition(chest)
    vrm.scene.worldToLocal(chest) // in the model's own frame, like the head: the peek moves the world
    const top = s.head.y + 0.17 // the head bone is the skull's base
    const height = (top - chest.y) / (FRAME.chest - FRAME.headTop)
    const middle = top + height * FRAME.headTop - height / 2
    const distance = height / 2 / Math.tan((camera.fov * Math.PI) / 360)
    camera.position.set(0, middle, distance)
    camera.lookAt(0, middle, 0)
    s.drop = (top - chest.y) * 1.25 // far enough down to hide the head behind the shelf
    if (s.ready < 0) s.ready = s.t
  }, [vrm, camera, size])

  useFrame((_, dt) => {
    if (!vrm) return
    const s = state.current
    s.t += dt
    const now = seconds()

    // The peek: up from behind the shelf, with a small tilt of the head that settles.
    const up = s.ready >= 0 ? rise(s.t, s.ready + PEEK.delay, PEEK.duration) : 0
    if (lift.current) lift.current.position.y = (up - 1) * s.drop

    // What to look at, in viewport pixels, then as a point in the scene.
    if (arc.current && now - books.current.at > REFRESH_S) {
      books.current = { points: [...arc.current.querySelectorAll('.arc-book')].map(centre), at: now }
    }
    const look = gazeTarget(now, cursor.current, books.current.points, pointed.current ? centre(pointed.current) : null)
    if (look) {
      const rect = gl.domElement.getBoundingClientRect()
      tools.ndc.set(((look.x - rect.left) / rect.width) * 2 - 1, -((look.y - rect.top) / rect.height) * 2 + 1)
      tools.ray.setFromCamera(tools.ndc, camera)
      if (tools.ray.ray.intersectPlane(tools.plane, tools.hit)) tools.target.position.copy(tools.hit)
    }

    // Head and neck turn toward it (in the model's own frame), quicker for a pointed book.
    const local = vrm.scene.worldToLocal(tools.local.copy(tools.target.position))
    const want = aim(s.head, local)
    const tau = look?.mode === 'book' ? 0.12 : look?.mode === 'cursor' ? 0.16 : 0.4
    s.yaw = approach(s.yaw, want.yaw, dt, tau)
    s.pitch = approach(s.pitch, want.pitch, dt, tau)
    const tilt = (1 - Math.min(up, 1)) * 0.22 + Math.sin(s.t * 0.7) * 0.015
    const breathe = Math.sin(s.t * 1.6) * 0.012
    const chest = bone(vrm, 'chest') ?? bone(vrm, 'spine')
    if (chest) chest.rotation.set(breathe - s.pitch * SHARE.spine, s.yaw * SHARE.spine, 0)
    bone(vrm, 'neck')?.rotation.set(-s.pitch * SHARE.neck, s.yaw * SHARE.neck, 0)
    bone(vrm, 'head')?.rotation.set(-s.pitch * SHARE.head, s.yaw * SHARE.head, tilt)

    const blink = blinkAt(s.t, s.nextBlink)
    s.nextBlink = blink.next
    s.smile = approach(s.smile, SMILE[look?.mode ?? 'browse'], dt, 0.25)
    const face = vrm.expressionManager
    face?.setValue('blink', blink.closed)
    face?.setValue('happy', s.smile)

    vrm.update(dt)
  })

  return vrm ? (
    <group ref={lift} position-y={-5 /* hidden until the first frame places it */}>
      <primitive object={vrm.scene} />
    </group>
  ) : null
}

export default function Character(props: Props) {
  return (
    <Canvas
      camera={{ fov: 22, near: 0.1, far: 20, position: [0, 1.3, 2] }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      aria-hidden="true"
    >
      <ambientLight intensity={0.75} color="#ffffff" />
      <directionalLight position={[-1.2, 1.8, 2]} intensity={1.0} color="#fff3e6" />
      <directionalLight position={[1.6, 1.4, -1.2]} intensity={0.7} color="#dfe6ff" />
      <Model {...props} />
    </Canvas>
  )
}

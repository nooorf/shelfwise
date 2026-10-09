// The assistant's face (design doc §21.4): the talking avatar when the device allows it, else a
// breathing orb. Both show the same states: idle, listening, thinking, speaking. The avatar
// is lazy-loaded (three.js is big); everything that can go wrong with it falls back to the
// orb (avatar/choice.ts). Both are decoration for screen readers, which hear each turn from
// the announcer instead.
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'

import { findModel, hasWebGL, ORB_NOTES, orbReason } from '../avatar/choice'
import type { Fallback } from '../avatar/AvatarStage'
import { speech } from '../session/useConversation'
import type { Status } from '../session/store'

const AvatarStage = lazy(() => import('../avatar/AvatarStage'))

const LABELS: Record<Status, string> = {
  starting: 'Connecting',
  ready: 'Ready',
  listening: 'Listening',
  searching: 'Thinking',
  writing: 'Writing',
  speaking: 'Speaking',
  offline: 'Offline: is the API running?',
}

const AVATAR_KEY = 'shelfwise.avatar'

function readWanted(): boolean {
  try {
    return globalThis.localStorage?.getItem(AVATAR_KEY) !== 'off'
  } catch {
    return true
  }
}

function Orb({ status }: { status: Status }) {
  const busy = status === 'searching' || status === 'writing' || status === 'speaking'
  return (
    <div className="relative size-12 shrink-0" aria-hidden="true">
      <div
        className={`absolute inset-0 rounded-full ${status === 'offline' ? 'bg-quiet-soft' : 'bg-accent'}`}
        style={{ animation: busy ? 'orb-breathe 1.2s ease-in-out infinite' : 'orb-breathe 4s ease-in-out infinite' }}
      />
      {status === 'searching' && (
        <div
          className="absolute -inset-1 rounded-full border-2 border-accent border-t-transparent"
          style={{ animation: 'orb-think 1s linear infinite' }}
        />
      )}
    </div>
  )
}

export function AvatarSlot({ status }: { status: Status }) {
  const [wanted, setWanted] = useState(readWanted)
  const [model, setModel] = useState<string | null | undefined>(undefined) // undefined: looking
  const [failed, setFailed] = useState<Fallback | null>(null)
  const [ready, setReady] = useState(false)
  const [env] = useState(() => ({
    webgl: hasWebGL(),
    reducedMotion: globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  }))

  useEffect(() => {
    let live = true
    void findModel().then((url) => live && setModel(url))
    return () => {
      live = false
    }
  }, [])

  const reason = model === undefined ? 'missing' : orbReason({ wanted, ...env, model, failed })
  const onFallback = useCallback((why: Fallback) => setFailed(why), [])
  const onReady = useCallback(() => setReady(true), [])
  const analyser = useCallback(() => ({ node: speech.analyser, sampleRate: speech.sampleRate }), [])

  const toggle = () => {
    const next = !wanted
    setWanted(next)
    setFailed(null)
    try {
      globalThis.localStorage?.setItem(AVATAR_KEY, next ? 'on' : 'off')
    } catch {
      // not remembered
    }
  }

  const label = <span className="text-sm text-muted">{LABELS[status]}</span>
  const switcher = (
    <button
      type="button"
      onClick={toggle}
      aria-pressed={wanted}
      title={reason && reason !== 'off' ? ORB_NOTES[reason] : undefined}
      className="text-xs text-muted hover:text-ink"
    >
      {wanted ? 'Avatar on' : 'Avatar off'}
    </button>
  )

  if (reason === null && model) {
    return (
      <div className="flex flex-col gap-1">
        <div className="relative h-56 overflow-hidden rounded-lg bg-card md:h-64" data-avatar={ready ? 'ready' : 'loading'}>
          <Suspense fallback={null}>
            <AvatarStage url={model} status={status} analyser={analyser} onFallback={onFallback} onReady={onReady} />
          </Suspense>
          {!ready && <div className="absolute inset-0 grid place-items-center"><Orb status={status} /></div>}
        </div>
        <div className="flex items-center justify-between">
          {label}
          {switcher}
        </div>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-3">
      <Orb status={status} />
      {label}
      <span className="ml-auto">{model !== undefined && switcher}</span>
    </div>
  )
}

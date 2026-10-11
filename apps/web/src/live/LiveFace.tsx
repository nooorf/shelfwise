// The assistant's face on the live page, large: the talking avatar when the device allows it,
// else a breathing orb (avatar/choice.ts says why). Both show the same states. The avatar is
// lazy-loaded with three.js; a failed or slow load hands over to the orb. Decoration for screen
// readers, which hear each turn from the announcer. The page holds the on/off setting
// (`wanted`) with its other switches; `onReason` tells it why the orb shows, for that switch.
import { lazy, Suspense, useCallback, useEffect, useState } from 'react'

import type { Fallback } from '../avatar/AvatarStage'
import { findModel, hasWebGL, orbReason } from '../avatar/choice'
import type { OrbReason } from '../avatar/choice'
import type { Status } from '../session/store'
import { speech } from '../session/useConversation'

const AvatarStage = lazy(() => import('../avatar/AvatarStage'))

function Orb({ status }: { status: Status }) {
  return <div className="live-orb" data-status={status} aria-hidden="true" />
}

interface Props {
  status: Status
  wanted: boolean
  onReason: (reason: OrbReason | null) => void
}

export function LiveFace({ status, wanted, onReason }: Props) {
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

  useEffect(() => onReason(model === undefined ? null : reason), [model, reason, onReason])

  return (
    <div className="live-face">
      {reason === null && model ? (
        <div className="live-avatar" data-avatar={ready ? 'ready' : 'loading'}>
          <Suspense fallback={null}>
            <AvatarStage url={model} status={status} analyser={analyser} onFallback={onFallback} onReady={onReady} distance={2.25} />
          </Suspense>
          {!ready && <Orb status={status} />}
        </div>
      ) : (
        <Orb status={status} />
      )}
    </div>
  )
}

// Loading a VRM model, shared by the talking avatar and the landing page's character: the
// model ready to show, facing the camera with its arms down out of the T-pose.
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm'
import type { VRM, VRMHumanBoneName } from '@pixiv/three-vrm'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

export function bone(vrm: VRM, name: VRMHumanBoneName) {
  return vrm.humanoid.getNormalizedBoneNode(name)
}

export async function loadVrm(url: string): Promise<VRM> {
  const loader = new GLTFLoader()
  loader.register((parser) => new VRMLoaderPlugin(parser))
  const gltf = await loader.loadAsync(url)
  const vrm = gltf.userData.vrm as VRM | undefined
  if (!vrm) throw new Error(`${url} is not a VRM model`)
  VRMUtils.removeUnnecessaryVertices(gltf.scene)
  VRMUtils.combineSkeletons(gltf.scene)
  VRMUtils.rotateVRM0(vrm) // VRM 0.x faces away; 1.0 already faces the camera
  bone(vrm, 'leftUpperArm')?.rotation.set(0, 0, -1.2) // out of the T-pose
  bone(vrm, 'rightUpperArm')?.rotation.set(0, 0, 1.2)
  bone(vrm, 'leftLowerArm')?.rotation.set(0, 0, -0.15)
  bone(vrm, 'rightLowerArm')?.rotation.set(0, 0, 0.15)
  vrm.update(0)
  return vrm
}

/** Seconds until the next blink and the eyelids' closure now (0-1): a blink every 2.5-6 s,
 * closing and opening over the last 150 ms. */
export function blinkAt(t: number, nextBlink: number): { next: number; closed: number } {
  const next = t >= nextBlink ? t + 2.5 + Math.random() * 3.5 : nextBlink
  const until = next - t
  return { next, closed: until < 0.15 ? Math.sin((1 - until / 0.15) * Math.PI) : 0 }
}

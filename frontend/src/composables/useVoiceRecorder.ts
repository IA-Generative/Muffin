import { ref } from 'vue'
import { pickRecorderType } from '../utils/voice'

export interface Recording {
  blob: Blob
  seconds: number
}

export class RecorderError extends Error {}

const isSupported =
  typeof window !== 'undefined' &&
  typeof MediaRecorder !== 'undefined' &&
  typeof navigator !== 'undefined' &&
  !!navigator.mediaDevices?.getUserMedia

function describe(error: unknown): string {
  const name = error instanceof DOMException ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Accès au micro refusé - autorisez-le dans les paramètres du navigateur pour dicter un message.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'Aucun micro n’a été trouvé sur cet appareil.'
  if (name === 'NotReadableError') return 'Le micro est utilisé par une autre application.'
  return 'L’enregistrement n’a pas pu démarrer. Réessayez, ou écrivez votre message.'
}

// L'enregistreur du micro (#517) : on démarre, on arrête (ou on annule), et on obtient le fichier - sans rien envoyer.
// Une seule instance à la fois dans la page (un seul micro) : l'état est partagé, comme pour la dictée du navigateur.
const isRecording = ref(false)
const elapsed = ref(0)
// 0 à 1 : le niveau sonore du moment, pour montrer que le micro entend.
const level = ref(0)

let recorder: MediaRecorder | null = null
let stream: MediaStream | null = null
let chunks: Blob[] = []
let startedAt = 0
let timer: ReturnType<typeof setInterval> | null = null
let audioContext: AudioContext | null = null
let meter: ReturnType<typeof setInterval> | null = null

function release() {
  if (timer) clearInterval(timer)
  if (meter) clearInterval(meter)
  timer = meter = null
  stream?.getTracks().forEach((track) => track.stop())
  void audioContext?.close().catch(() => undefined)
  stream = null
  audioContext = null
  recorder = null
  chunks = []
  isRecording.value = false
  elapsed.value = 0
  level.value = 0
}

function watchLevel(source: MediaStream) {
  try {
    const Context = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Context) return
    audioContext = new Context()
    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 512
    audioContext.createMediaStreamSource(source).connect(analyser)
    const samples = new Uint8Array(analyser.fftSize)
    meter = setInterval(() => {
      analyser.getByteTimeDomainData(samples)
      let peak = 0
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample - 128))
      level.value = Math.min(1, peak / 64)
    }, 100)
  } catch {
    // Sans mesure du niveau, l'enregistrement marche : seul l'indicateur manque.
  }
}

// `onLimit` : appelé quand la durée maximale est atteinte - l'enregistreur ne s'arrête pas lui-même, c'est l'appelant qui
// décide (il arrête, transcrit, annonce).
async function start(maxSeconds: number, onLimit: () => void): Promise<void> {
  if (!isSupported) throw new RecorderError('L’enregistrement n’est pas disponible sur ce navigateur.')
  if (isRecording.value) return
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (error) {
    throw new RecorderError(describe(error))
  }
  const type = pickRecorderType((candidate) => MediaRecorder.isTypeSupported(candidate))
  try {
    recorder = type ? new MediaRecorder(stream, { mimeType: type }) : new MediaRecorder(stream)
  } catch {
    release()
    throw new RecorderError('Ce navigateur ne sait pas enregistrer de l’audio.')
  }
  chunks = []
  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data)
  }
  recorder.start(1000)
  startedAt = Date.now()
  isRecording.value = true
  watchLevel(stream)
  timer = setInterval(() => {
    elapsed.value = (Date.now() - startedAt) / 1000
    if (elapsed.value >= maxSeconds) {
      if (timer) clearInterval(timer)
      timer = null
      onLimit()
    }
  }, 250)
}

function stop(): Promise<Recording | null> {
  const active = recorder
  if (!active || active.state === 'inactive') {
    release()
    return Promise.resolve(null)
  }
  return new Promise((resolve) => {
    active.onstop = () => {
      const seconds = (Date.now() - startedAt) / 1000
      const blob = new Blob(chunks, { type: active.mimeType || chunks[0]?.type || 'audio/webm' })
      release()
      resolve(blob.size > 0 ? { blob, seconds } : null)
    }
    active.stop()
  })
}

// Abandonne l'enregistrement : rien n'est gardé ni envoyé.
function cancel() {
  if (recorder && recorder.state !== 'inactive') {
    recorder.onstop = null
    recorder.stop()
  }
  release()
}

export function useVoiceRecorder() {
  return { isSupported, isRecording, elapsed, level, start, stop, cancel }
}

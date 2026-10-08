import { onMounted, onUnmounted, ref, watch, type Ref } from 'vue'
import { DraftError, useDocumentDraft, type DocumentDraft } from './useDocumentDraft'

interface Options {
  // Called after a validation went through: the document has a new revision and is being reindexed.
  onValidated?: () => void
  // Bring the review window up on its own when the job the user is waiting on finishes. Right where
  // they just asked for the edit (the revisions tab); not for a chat card, where a window popping
  // up in the middle of a conversation would be an interruption - the card shows the new state.
  openWhenReady?: boolean
}

// One user's session with a document's proposed edit (#169): the draft, polling it, and the actions
// on it. Shared by the revisions tab (where an edit is requested) and the chat card (where the
// research agent delegated one) - two entry points to the same draft, so the same logic.
//
// Reading the draft renews its lock server-side, so polling is also what keeps it alive: fast while
// a job runs, slow otherwise.
export function useDraftSession(collectionId: Ref<string>, documentId: Ref<string>, options: Options = {}) {
  const { openWhenReady = true } = options
  const api = useDocumentDraft()

  const draft = ref<DocumentDraft | null>(null)
  const loaded = ref(false)
  const busy = ref(false)
  const error = ref<string | null>(null)
  const reviewing = ref(false)
  // The user validated it from here: the card says so instead of "no such proposal" once the draft is gone.
  const validated = ref(false)

  function message(failure: unknown): string {
    return failure instanceof DraftError ? failure.message : 'L’opération a échoué.'
  }

  async function load() {
    try {
      draft.value = await api.fetchDraft(collectionId.value, documentId.value)
    } catch {
      // A failed poll is retried on the next tick - the draft itself is unaffected.
    }
    loaded.value = true
  }

  let timer: ReturnType<typeof setTimeout> | undefined
  function schedule() {
    timer = setTimeout(
      async () => {
        await load()
        schedule()
      },
      draft.value?.status === 'pending' ? 2000 : 10_000,
    )
  }

  onMounted(async () => {
    await load()
    schedule()
  })
  onUnmounted(() => clearTimeout(timer))

  // The job the user is waiting on just finished: bring the result up without making them look for it.
  watch(draft, (now, before) => {
    if (openWhenReady && before?.status === 'pending' && now && now.status !== 'pending') reviewing.value = true
    if (!now) reviewing.value = false
  })

  // Runs an action on the draft; a returned draft replaces the current one.
  async function run(action: () => Promise<DocumentDraft | void>) {
    busy.value = true
    error.value = null
    try {
      const result = await action()
      if (result) draft.value = result
    } catch (failure) {
      error.value = message(failure)
      await load() // it may have lapsed or moved on: show what is true now
    } finally {
      busy.value = false
    }
  }

  const request = (prompt: string) =>
    run(async () => {
      const created = await api.createDraft(collectionId.value, documentId.value, prompt)
      reviewing.value = true
      return created
    })

  const adjust = (prompt: string) => run(() => api.adjustDraft(collectionId.value, documentId.value, prompt))
  const upload = (imageId: string, file: File) =>
    run(() => api.uploadImage(collectionId.value, documentId.value, imageId, file))
  const insertImages = () => run(() => api.insertImages(collectionId.value, documentId.value))

  const refuse = () =>
    run(async () => {
      await api.refuseDraft(collectionId.value, documentId.value)
      draft.value = null
      reviewing.value = false
    })

  const validate = () =>
    run(async () => {
      await api.validateDraft(collectionId.value, documentId.value)
      draft.value = null
      reviewing.value = false
      validated.value = true
      options.onValidated?.()
    })

  return { draft, loaded, busy, error, reviewing, validated, request, adjust, upload, insertImages, refuse, validate }
}

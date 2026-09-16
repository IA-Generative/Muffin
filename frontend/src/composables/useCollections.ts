import { computed, ref } from 'vue'
import { router } from '../router'
import type {
  ChunkingSettings,
  Chunk,
  Collection,
  CollectionDocument,
  Entity,
  EntityType,
  EvaluationResult,
  EvaluationRun,
  FieldStamp,
  PipelineInstructions,
  QaPair,
  Relation,
} from '../types/collection'
import { useCurrentUser } from './useCurrentUser'

function doc(name: string, type: CollectionDocument['type'], status: CollectionDocument['status']): CollectionDocument {
  return { id: crypto.randomUUID(), name, type, status, progress: status === 'indexed' ? 100 : 0 }
}

function stamp(updatedBy: string, updatedAt: string): FieldStamp {
  return { updatedBy, updatedAt }
}

function qa(
  question: string,
  answer: string,
  opts: { source?: string; origin?: QaPair['origin']; validated?: boolean } = {},
): QaPair {
  return {
    id: crypto.randomUUID(),
    question,
    answer,
    source: opts.source,
    origin: opts.origin ?? 'generated',
    validated: opts.validated ?? false,
  }
}

function relation(from: string, to: string, type: string): Relation {
  return { id: crypto.randomUUID(), from, to, type }
}

function entity(name: string, type: EntityType, mentions: number): Entity {
  return { id: crypto.randomUUID(), name, type, mentions }
}

function chunk(documentName: string, index: number, text: string): Chunk {
  return { id: crypto.randomUUID(), documentName, index, text, tokenCount: Math.round(text.length / 4) }
}

function defaultChunkingSettings(): ChunkingSettings {
  return { strategy: 'paragraph', chunkSize: 512, chunkOverlap: 50 }
}

function defaultInstructions(): PipelineInstructions {
  return { qa: '', extraction: '', chunking: '', tagging: '' }
}

// Mock jusqu'au branchement du backend.
const collections = ref<Collection[]>([
  {
    id: 'c1',
    name: 'Projets',
    description: 'Notes et documents liés aux projets en cours.',
    descriptionMeta: stamp('Michou', '2026-09-15T10:00:00Z'),
    tags: ['interne', 'travail'],
    tagsMeta: stamp('Michou', '2026-09-12T09:00:00Z'),
    updatedAt: '2026-09-15T10:00:00Z',
    documents: [
      doc('plan-projet.pdf', 'file', 'indexed'),
      doc('budget.xlsx', 'file', 'indexed'),
      doc('roadmap.pdf', 'file', 'indexed'),
      doc('https://intranet.example.fr/projets', 'url', 'indexed'),
    ],
    qaPairs: [
      qa('Quel est le budget alloué au projet ?', 'Le budget prévisionnel est détaillé dans budget.xlsx.', {
        source: 'budget.xlsx',
      }),
      qa('Qui pilote le projet ?', "L'équipe projet est listée dans plan-projet.pdf, section 2.", {
        source: 'plan-projet.pdf',
        validated: true,
      }),
    ],
    entities: [
      entity('Michou', 'personne', 4),
      entity('Direction des systèmes d\'information', 'organisation', 2),
      entity('30 juin 2027', 'date', 1),
    ],
    relations: [
      relation('plan-projet.pdf', 'budget.xlsx', 'référence'),
      relation('roadmap.pdf', 'plan-projet.pdf', 'découle de'),
    ],
    chunks: [
      chunk('plan-projet.pdf', 0, "Le projet vise à moderniser l'infrastructure interne sur 12 mois, avec trois jalons majeurs..."),
      chunk('plan-projet.pdf', 1, "L'équipe est composée de 6 personnes réparties sur le développement, le design et la conduite du changement..."),
      chunk('budget.xlsx', 0, 'Budget total : 240 000€, répartis entre infrastructure (60%), prestations externes (30%) et formation (10%).'),
    ],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c2',
    name: 'Notes',
    description: 'Notes personnelles diverses.',
    descriptionMeta: stamp('Michou', '2026-09-10T10:00:00Z'),
    tags: ['personnel'],
    tagsMeta: stamp('Michou', '2026-09-10T10:00:00Z'),
    updatedAt: '2026-09-10T10:00:00Z',
    documents: Array.from({ length: 12 }, (_, i) =>
      doc(`note-${i + 1}.md`, 'file', i < 9 ? 'indexed' : 'pending'),
    ),
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c3',
    name: 'Marchés publics',
    description: "Cahiers des charges et appels d'offres suivis par la direction.",
    descriptionMeta: stamp('Michou', '2026-09-14T10:00:00Z'),
    tags: ['juridique', 'marchés'],
    tagsMeta: stamp('Michou', '2026-09-02T10:00:00Z'),
    updatedAt: '2026-09-14T10:00:00Z',
    documents: Array.from({ length: 27 }, (_, i) => doc(`marche-${i + 1}.pdf`, 'file', 'indexed')),
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c4',
    name: 'RGAA & accessibilité',
    description: "Référentiels et rapports d'audit accessibilité.",
    descriptionMeta: stamp('Michou', '2026-08-30T10:00:00Z'),
    tags: ['accessibilité', 'qualité'],
    tagsMeta: stamp('Michou', '2026-08-30T10:00:00Z'),
    updatedAt: '2026-08-30T10:00:00Z',
    documents: [
      ...Array.from({ length: 5 }, (_, i) => doc(`audit-${i + 1}.pdf`, 'file', 'indexed')),
      ...Array.from({ length: 3 }, (_, i) => doc(`referentiel-${i + 1}.pdf`, 'file', 'pending')),
    ],
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c5',
    name: 'RH',
    description: 'Procédures internes ressources humaines.',
    descriptionMeta: stamp('Michou', '2026-09-01T10:00:00Z'),
    tags: ['rh', 'interne'],
    tagsMeta: stamp('Michou', '2026-09-01T10:00:00Z'),
    updatedAt: '2026-09-01T10:00:00Z',
    documents: Array.from({ length: 15 }, (_, i) => doc(`procedure-${i + 1}.pdf`, 'file', 'indexed')),
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c6',
    name: 'Sécurité',
    description: "Politiques de sécurité et rapports d'audit.",
    descriptionMeta: stamp('Michou', '2026-09-16T08:00:00Z'),
    tags: ['sécurité', 'audit'],
    tagsMeta: stamp('Michou', '2026-09-05T08:00:00Z'),
    updatedAt: '2026-09-16T08:00:00Z',
    documents: [
      doc('politique-securite.pdf', 'file', 'indexed'),
      doc('rapport-audit-2026.pdf', 'file', 'indexed'),
      doc('plan-continuite.pdf', 'file', 'pending'),
      doc('https://cert.ssi.gouv.fr', 'url', 'pending'),
      doc('procedure-incident.pdf', 'file', 'pending'),
      doc('charte-securite.pdf', 'file', 'pending'),
    ],
    qaPairs: [
      qa(
        'Que faire en cas de suspicion de compromission ?',
        'Suivre procedure-incident.pdf : isoler le poste puis prévenir le RSSI.',
        { source: 'procedure-incident.pdf' },
      ),
    ],
    entities: [
      entity('RSSI', 'personne', 3),
      entity('CERT-FR', 'organisation', 2),
    ],
    relations: [relation('rapport-audit-2026.pdf', 'politique-securite.pdf', 'contrôle la conformité à')],
    chunks: [
      chunk('politique-securite.pdf', 0, "La politique de sécurité s'applique à l'ensemble des systèmes d'information de l'organisation..."),
      chunk('rapport-audit-2026.pdf', 0, "L'audit 2026 relève 3 non-conformités majeures et 8 mineures, détaillées en annexe..."),
    ],
    chunkingSettings: { ...defaultChunkingSettings(), strategy: 'semantic', chunkSize: 384 },
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
  {
    id: 'c7',
    name: 'Communication externe',
    description: 'Supports de communication et éléments de langage.',
    descriptionMeta: stamp('Michou', '2026-07-20T10:00:00Z'),
    tags: ['communication'],
    tagsMeta: stamp('Michou', '2026-07-20T10:00:00Z'),
    updatedAt: '2026-07-20T10:00:00Z',
    documents: Array.from({ length: 3 }, (_, i) => doc(`support-${i + 1}.pdf`, 'file', 'indexed')),
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  },
])

const activeCollectionId = ref<string>()
const activeCollection = computed(() =>
  collections.value.find((collection) => collection.id === activeCollectionId.value),
)

// `navigate: false` is used when a route change already triggered this (see
// CollectionsView's route watcher) - pushing again there would just double the entry.
function openCollection(id: string, options: { navigate?: boolean } = {}) {
  activeCollectionId.value = id
  const target = `/collections/${id}`
  if (options.navigate !== false && router.currentRoute.value.fullPath !== target) {
    router.push(target)
  }
}

function closeCollection(options: { navigate?: boolean } = {}) {
  activeCollectionId.value = undefined
  if (options.navigate !== false && router.currentRoute.value.path !== '/collections') {
    router.push('/collections')
  }
}

function createCollection() {
  const { user } = useCurrentUser()
  const now = new Date().toISOString()
  const id = crypto.randomUUID()
  collections.value.unshift({
    id,
    name: 'Nouvelle collection',
    description: '',
    descriptionMeta: stamp(user.value?.name ?? 'Anonyme', now),
    tags: [],
    tagsMeta: stamp(user.value?.name ?? 'Anonyme', now),
    updatedAt: now,
    documents: [],
    qaPairs: [],
    entities: [],
    relations: [],
    chunks: [],
    chunkingSettings: defaultChunkingSettings(),
    embeddingModel: 'text-embedding-3-small',
    reindexRequired: false,
    instructions: defaultInstructions(),
    evaluationRuns: [],
  })
  openCollection(id)
}

function updateName(id: string, name: string) {
  const collection = collections.value.find((item) => item.id === id)
  if (!collection || !name.trim()) return
  collection.name = name.trim()
  collection.updatedAt = new Date().toISOString()
}

function updateDescription(id: string, description: string) {
  const { user } = useCurrentUser()
  const collection = collections.value.find((item) => item.id === id)
  if (!collection) return
  const now = new Date().toISOString()
  collection.description = description
  collection.descriptionMeta = stamp(user.value?.name ?? 'Anonyme', now)
  collection.updatedAt = now
}

function updateTags(id: string, tags: string[]) {
  const { user } = useCurrentUser()
  const collection = collections.value.find((item) => item.id === id)
  if (!collection) return
  const now = new Date().toISOString()
  collection.tags = tags
  collection.tagsMeta = stamp(user.value?.name ?? 'Anonyme', now)
  collection.updatedAt = now
}

function deleteCollection(id: string) {
  collections.value = collections.value.filter((item) => item.id !== id)
  if (activeCollectionId.value === id) closeCollection()
}

// Pas de backend : on simule un pipeline d'indexation progressif côté client.
function simulateIndexing(collectionId: string, documentId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  const document = collection?.documents.find((item) => item.id === documentId)
  if (!document) return

  document.status = 'indexing'
  const interval = setInterval(() => {
    document.progress = Math.min(100, document.progress + Math.round(10 + Math.random() * 20))
    if (document.progress >= 100) {
      document.status = 'indexed'
      collection!.updatedAt = new Date().toISOString()
      clearInterval(interval)
    }
  }, 400)
}

function addDocuments(collectionId: string, files: File[]) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  for (const file of files) {
    const newDoc = doc(file.name, 'file', 'pending')
    collection.documents.push(newDoc)
    simulateIndexing(collectionId, newDoc.id)
  }
  collection.updatedAt = new Date().toISOString()
}

function addUrl(collectionId: string, url: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection || !url.trim()) return
  const newDoc = doc(url.trim(), 'url', 'pending')
  collection.documents.push(newDoc)
  collection.updatedAt = new Date().toISOString()
  simulateIndexing(collectionId, newDoc.id)
}

function removeDocument(collectionId: string, documentId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.documents = collection.documents.filter((item) => item.id !== documentId)
}

function addQaPair(collectionId: string, question: string, answer: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection || !question.trim() || !answer.trim()) return
  // Écrite à la main dans l'UI : considérée validée d'office, pas de source document.
  collection.qaPairs.push(qa(question.trim(), answer.trim(), { origin: 'manual', validated: true }))
  collection.updatedAt = new Date().toISOString()
}

function removeQaPair(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.qaPairs = collection.qaPairs.filter((item) => item.id !== qaPairId)
}

function toggleQaValidation(collectionId: string, qaPairId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  const pair = collection?.qaPairs.find((item) => item.id === qaPairId)
  if (!pair) return
  pair.validated = !pair.validated
}

function updateChunkingSettings(collectionId: string, settings: ChunkingSettings) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.chunkingSettings = settings
  collection.updatedAt = new Date().toISOString()
}

// Changer de modèle d'embedding invalide les vecteurs déjà calculés : posé à
// part du reste du chunking pour que ce seul changement déclenche le besoin
// de réindexation, sans en imposer un pour un simple ajustement de stratégie.
function updateEmbeddingModel(collectionId: string, model: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  if (collection.embeddingModel !== model) collection.reindexRequired = true
  collection.embeddingModel = model
  collection.updatedAt = new Date().toISOString()
}

// Pas de backend : on rejoue simplement l'indexation de tous les documents.
function reindexCollection(collectionId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.reindexRequired = false
  for (const document of collection.documents) {
    document.status = 'pending'
    document.progress = 0
    simulateIndexing(collectionId, document.id)
  }
}

function updateInstructionField(collectionId: string, field: keyof PipelineInstructions, value: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return
  collection.instructions[field] = value
  collection.updatedAt = new Date().toISOString()
}

// Pas de backend : score chaque Q/R validée avec des valeurs plausibles au
// lieu d'interroger le vrai pipeline de retrieval. Les non-validées sont
// exclues, sur demande explicite - une paire pas encore relue par un humain
// ne doit pas fausser une mesure de qualité.
const EVAL_K = 5
// Pas encore de champ dans l'UI pour choisir le modèle de génération : fixé
// ici en attendant, mais déjà tracé par run pour comparer plusieurs modèles
// plus tard sans perdre l'historique des runs passés.
const EVAL_LLM_MODEL = 'gpt-4o-mini'

function mockGeneratedAnswer(pair: QaPair): string {
  // ~1 run sur 5 simule une réponse dégradée, pour que l'écran d'évaluation
  // montre autre chose qu'un alignement parfait entre réponse générée et attendue.
  return Math.random() < 0.2
    ? "Je n'ai pas trouvé d'information suffisamment fiable pour répondre avec certitude."
    : pair.answer
}

function mockRetrievedSources(collection: Collection, pair: QaPair): string[] {
  const others = collection.documents.map((document) => document.name).filter((name) => name !== pair.source)
  const extra = others[Math.floor(Math.random() * others.length)]
  return [pair.source, extra].filter((name): name is string => Boolean(name))
}

function runEvaluation(collectionId: string) {
  const collection = collections.value.find((item) => item.id === collectionId)
  if (!collection) return

  const validated = collection.qaPairs.filter((pair) => pair.validated)
  if (!validated.length) return

  const results: EvaluationResult[] = validated.map((pair) => {
    const precisionAtK = Math.round((0.6 + Math.random() * 0.4) * 100) / 100
    const recallAtK = Math.round((0.55 + Math.random() * 0.45) * 100) / 100
    const reciprocalRank = Math.round((0.5 + Math.random() * 0.5) * 100) / 100
    const ndcg = Math.round((0.6 + Math.random() * 0.4) * 100) / 100
    return {
      qaPairId: pair.id,
      question: pair.question,
      expectedAnswer: pair.answer,
      generatedAnswer: mockGeneratedAnswer(pair),
      retrievedSources: mockRetrievedSources(collection, pair),
      precisionAtK,
      recallAtK,
      reciprocalRank,
      ndcg,
    }
  })

  const average = (values: number[]) =>
    Math.round((values.reduce((sum, value) => sum + value, 0) / values.length) * 100) / 100

  const run: EvaluationRun = {
    id: crypto.randomUUID(),
    runAt: new Date().toISOString(),
    k: EVAL_K,
    pairCount: results.length,
    llmModel: EVAL_LLM_MODEL,
    // Copie indépendante : si la config change après coup, ce run garde la
    // trace de ce qui a réellement produit ces résultats.
    chunkingSnapshot: { ...collection.chunkingSettings, embeddingModel: collection.embeddingModel },
    metrics: {
      precisionAtK: average(results.map((result) => result.precisionAtK)),
      recallAtK: average(results.map((result) => result.recallAtK)),
      mrr: average(results.map((result) => result.reciprocalRank)),
      ndcg: average(results.map((result) => result.ndcg)),
    },
    results,
  }

  collection.evaluationRuns.unshift(run)
}

export function useCollections() {
  return {
    collections,
    activeCollection,
    openCollection,
    closeCollection,
    createCollection,
    updateName,
    updateDescription,
    updateTags,
    deleteCollection,
    addDocuments,
    addUrl,
    removeDocument,
    addQaPair,
    removeQaPair,
    toggleQaValidation,
    updateChunkingSettings,
    updateEmbeddingModel,
    reindexCollection,
    updateInstructionField,
    runEvaluation,
  }
}

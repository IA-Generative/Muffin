<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { type ImageSettingsDraft, type ImageTestResult, useAdminImages } from '../composables/useAdminImages'

const { settings, isLoading, error, loadImageSettings, saveImageSettings, testImageSettings } = useAdminImages()

const MIB = 1024 * 1024
const QUALITIES = ['', 'auto', 'low', 'medium', 'high', 'standard', 'hd']

const draft = reactive<ImageSettingsDraft>({
  enabled: false,
  baseUrl: '',
  apiKey: '',
  clearKey: false,
  model: '',
  editModel: '',
  size: '1024x1024',
  quality: '',
  dailyLimit: 20,
  maxImageBytes: 8 * MIB,
  allowedGroups: [],
})
// La taille se règle en Mo, les groupes en une liste séparée par des virgules : ce qu'on tape n'est pas ce qu'on envoie.
const maxMib = ref(8)
const groupsText = ref('')
const saved = ref(false)
const testing = ref(false)
const testResult = ref<ImageTestResult | null>(null)
const testUnreachable = ref(false)

onMounted(loadImageSettings)

watch(
  settings,
  (value) => {
    if (!value) return
    draft.enabled = value.enabled
    // Vide : l'adresse du hub. On ne recopie pas l'adresse du hub dans le champ, pour ne pas la figer.
    draft.baseUrl = value.usesHubAddress ? '' : (value.baseUrl ?? '')
    draft.apiKey = ''
    draft.clearKey = false
    draft.model = value.model ?? ''
    draft.editModel = value.editModel ?? ''
    draft.size = value.size
    draft.quality = value.quality ?? ''
    draft.dailyLimit = value.dailyLimit
    maxMib.value = Math.round((value.maxImageBytes / MIB) * 10) / 10
    groupsText.value = value.allowedGroups.join(', ')
  },
  { immediate: true },
)

const keyHint = computed(() => {
  if (draft.clearKey) return 'La clé enregistrée sera oubliée.'
  if (settings.value?.hasKey) return 'Une clé est enregistrée. Elle ne s’affiche jamais : saisissez-en une autre pour la remplacer.'
  if (!draft.baseUrl.trim()) return 'Vide : la clé du hub est utilisée. Elle n’est jamais envoyée à une autre adresse.'
  return 'Une autre adresse que celle du hub demande sa propre clé.'
})

async function save() {
  draft.maxImageBytes = Math.round(maxMib.value * MIB)
  draft.allowedGroups = groupsText.value
    .split(',')
    .map((group) => group.trim())
    .filter(Boolean)
  saved.value = await saveImageSettings(draft)
  if (saved.value) setTimeout(() => (saved.value = false), 2000)
}

// Teste les réglages enregistrés, pas ceux qu'on est en train de taper : on enregistre d'abord.
async function test() {
  testing.value = true
  testResult.value = null
  testUnreachable.value = false
  const result = await testImageSettings()
  testResult.value = result
  testUnreachable.value = result === null
  testing.value = false
}
</script>

<template>
  <section class="admin-view">
    <router-link to="/admin" class="admin-view__back">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5 3 12l7.5-7.5M3 12h18" />
      </svg>
      Administration
    </router-link>
    <div class="admin-view__header">
      <h1>Génération d’images</h1>
    </div>
    <p class="admin-view__intro">
      Facultative et <strong>désactivée par défaut</strong>. Quand elle est activée, les personnes autorisées peuvent
      demander une image dans le chat avec le mode « Image ». La description part vers le fournisseur choisi ci-dessous ;
      l’image est gardée par Muffin avec la conversation, lisible par son auteur seulement, et étiquetée « générée par IA ».
    </p>

    <p v-if="isLoading && !settings" class="admin-view__empty">Chargement…</p>

    <form v-else-if="settings" class="admin-card" @submit.prevent="save">
      <p v-if="error" class="admin-card__error" role="alert">{{ error }}</p>

      <div class="fr-checkbox-group">
        <input id="img-enabled" v-model="draft.enabled" type="checkbox" />
        <label class="fr-label" for="img-enabled">
          Activer la génération d’images
          <span class="fr-hint-text">Il faut un modèle ; sans activation, rien ne change et aucun appel n’est fait.</span>
        </label>
      </div>

      <div class="admin-card__field">
        <label for="img-base-url">Adresse du fournisseur</label>
        <input
          id="img-base-url"
          v-model="draft.baseUrl"
          class="fr-input"
          type="url"
          autocomplete="off"
          :placeholder="settings.hubAvailable ? 'Vide : celle du hub' : 'https://passerelle.exemple/v1'"
        />
        <p class="admin-card__hint">
          Une adresse compatible OpenAI, terminée par <code>/v1</code> (le hub, une passerelle LiteLLM, LocalAI…).
          <template v-if="settings.usesHubAddress && settings.baseUrl">Actuellement : {{ settings.baseUrl }}.</template>
        </p>
      </div>

      <div class="admin-card__field">
        <label for="img-api-key">Clé</label>
        <input
          id="img-api-key"
          v-model="draft.apiKey"
          class="fr-input"
          type="password"
          autocomplete="new-password"
          :placeholder="settings.hasKey ? '••••••••••••' : ''"
        />
        <p class="admin-card__hint">{{ keyHint }}</p>
        <div v-if="settings.hasKey" class="fr-checkbox-group fr-checkbox-group--sm">
          <input id="img-clear-key" v-model="draft.clearKey" type="checkbox" />
          <label class="fr-label" for="img-clear-key">Oublier la clé enregistrée</label>
        </div>
      </div>

      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="img-model">Modèle</label>
          <input id="img-model" v-model="draft.model" class="fr-input" type="text" autocomplete="off" placeholder="gpt-image-1" />
        </div>
        <div class="admin-card__field">
          <label for="img-edit-model">Modèle de retouche (facultatif)</label>
          <input id="img-edit-model" v-model="draft.editModel" class="fr-input" type="text" autocomplete="off" placeholder="Le même que pour générer" />
        </div>
        <div class="admin-card__field">
          <label for="img-size">Taille</label>
          <input id="img-size" v-model="draft.size" class="fr-input" type="text" autocomplete="off" placeholder="1024x1024" />
        </div>
        <div class="admin-card__field">
          <label for="img-quality">Qualité</label>
          <select id="img-quality" v-model="draft.quality" class="fr-select">
            <option v-for="quality in QUALITIES" :key="quality" :value="quality">{{ quality || 'Par défaut du modèle' }}</option>
          </select>
        </div>
      </div>
      <p class="admin-card__hint">
        Tailles acceptées selon le modèle : <code>dall-e-2</code> 256, 512 ou 1024 ; <code>dall-e-3</code> 1024×1024, 1792×1024
        ou 1024×1792 ; <code>gpt-image-*</code> <code>auto</code>, 1024×1024, 1536×1024 ou 1024×1536.
      </p>

      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="img-daily">Images par personne et par jour</label>
          <input id="img-daily" v-model.number="draft.dailyLimit" class="fr-input" type="number" min="1" max="1000" />
        </div>
        <div class="admin-card__field">
          <label for="img-max">Poids maximal d’une image (Mo)</label>
          <input id="img-max" v-model.number="maxMib" class="fr-input" type="number" min="0.1" step="0.5" />
        </div>
      </div>

      <div class="admin-card__field">
        <label for="img-groups">Groupes autorisés</label>
        <input id="img-groups" v-model="groupsText" class="fr-input" type="text" autocomplete="off" placeholder="Vide : tout le monde" />
        <p class="admin-card__hint">
          Noms de groupes séparés par des virgules. Un administrateur peut toujours générer des images.
        </p>
      </div>

      <div class="admin-card__footer">
        <span v-if="saved" class="admin-card__saved">Enregistré</span>
        <span class="admin-card__state" :class="{ 'admin-card__state--ready': settings.ready }">
          {{ settings.ready ? 'Prête : proposée aux personnes autorisées' : 'Non proposée dans le chat' }}
        </span>
        <button type="submit" class="fr-btn">Enregistrer</button>
      </div>
    </form>

    <div v-if="settings" class="admin-card admin-card--test">
      <h2 class="admin-card__title">Tester</h2>
      <p class="admin-card__intro">
        Fait une petite image avec les réglages <strong>enregistrés</strong> et dit combien de temps le fournisseur a mis, ou
        ce qui ne va pas (clé refusée, modèle inconnu, paramètre refusé…). L’image n’est pas gardée et ne compte dans le
        quota de personne.
      </p>
      <button type="button" class="fr-btn fr-btn--secondary" :disabled="testing" @click="test">
        {{ testing ? 'Génération en cours…' : 'Tester' }}
      </button>

      <p v-if="testUnreachable" class="admin-card__error" role="alert">Le serveur est inaccessible.</p>
      <div v-else-if="testResult" class="admin-card__result" role="status">
        <p v-if="testResult.ok" class="admin-card__saved">
          Image obtenue en {{ (testResult.durationMs / 1000).toFixed(1) }} s — {{ testResult.width }}×{{ testResult.height }},
          {{ testResult.contentType }}, {{ Math.round((testResult.sizeBytes ?? 0) / 1024) }} Ko, réponse en
          <code>{{ testResult.responseFormat }}</code>.
        </p>
        <p v-else class="admin-card__error">
          {{ testResult.message }} <span class="admin-card__code">({{ testResult.code }}, {{ (testResult.durationMs / 1000).toFixed(1) }} s)</span>
        </p>
        <img v-if="testResult.image" :src="testResult.image" alt="Image d’essai générée par IA" class="admin-card__preview" />
      </div>
    </div>

    <p v-else-if="error" class="admin-view__error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.admin-view {
  flex: 1;
  height: 100%;
  overflow-y: auto;
  padding: 2rem 2.5rem;
  box-sizing: border-box;
}

.admin-view__back {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  max-width: 48rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__header,
.admin-view__intro {
  max-width: 48rem;
  margin-left: auto;
  margin-right: auto;
}

.admin-view__header h1 {
  margin: 0;
}

.admin-view__intro {
  margin-top: 0.5rem;
  margin-bottom: 1.5rem;
  color: var(--text-mention-grey);
}

.admin-view__empty,
.admin-view__error {
  max-width: 48rem;
  margin: 3rem auto;
  text-align: center;
  color: var(--text-mention-grey);
}

.admin-view__error {
  color: var(--text-default-error);
}

.admin-card {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 48rem;
  margin: 0 auto 1.5rem;
  padding: 1.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.75rem;
  background: var(--background-default-grey);
  box-sizing: border-box;
}

.admin-card__title {
  margin: 0;
  font-size: 1.0625rem;
}

.admin-card__intro {
  margin: 0;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.admin-card__field {
  flex: 1;
  min-width: 9rem;
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.admin-card__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.admin-card__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.admin-card__hint {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.admin-card__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.admin-card__state {
  margin-right: auto;
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.admin-card__state--ready {
  color: var(--text-default-success);
}

.admin-card__saved {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.admin-card__error {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.admin-card__code {
  color: var(--text-mention-grey);
}

.admin-card__result {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.admin-card__preview {
  max-width: 16rem;
  height: auto;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}
</style>

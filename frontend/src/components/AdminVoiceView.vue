<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { type VoiceSettingsDraft, type VoiceTestResult, useAdminVoice } from '../composables/useAdminVoice'

const { settings, isLoading, error, loadVoiceSettings, saveVoiceSettings, testVoice, playSpeechSample } = useAdminVoice()

const MIB = 1024 * 1024
const FORMATS = ['mp3', 'wav', 'flac', 'opus', 'aac']

const draft = reactive<VoiceSettingsDraft>({
  sttEnabled: false,
  sttBaseUrl: '',
  sttApiKey: '',
  sttClearKey: false,
  sttModel: '',
  sttLanguage: 'auto',
  sttMaxSeconds: 300,
  sttMaxBytes: 25 * MIB,
  ttsEnabled: false,
  ttsBaseUrl: '',
  ttsApiKey: '',
  ttsClearKey: false,
  ttsModel: '',
  ttsVoice: '',
  ttsVoiceEn: '',
  ttsFormat: 'mp3',
  ttsMaxChars: 4000,
})
// Le poids se règle en Mo : ce qu'on tape n'est pas ce qu'on envoie.
const maxMib = ref(25)
const saved = ref(false)
const testing = ref<'transcription' | 'speech' | null>(null)
const results = reactive<{ transcription: VoiceTestResult | null; speech: VoiceTestResult | null }>({
  transcription: null,
  speech: null,
})
const unreachable = ref(false)
const played = ref<boolean | null>(null)

onMounted(loadVoiceSettings)

watch(
  settings,
  (value) => {
    if (!value) return
    draft.sttEnabled = value.sttEnabled
    // Vide : l'adresse du hub. On ne recopie pas l'adresse du hub dans le champ, pour ne pas la figer.
    draft.sttBaseUrl = value.sttUsesHubAddress ? '' : (value.sttBaseUrl ?? '')
    draft.sttApiKey = ''
    draft.sttClearKey = false
    draft.sttModel = value.sttModel ?? ''
    draft.sttLanguage = value.sttLanguage
    draft.sttMaxSeconds = value.sttMaxSeconds
    maxMib.value = Math.round((value.sttMaxBytes / MIB) * 10) / 10
    draft.ttsEnabled = value.ttsEnabled
    draft.ttsBaseUrl = value.ttsUsesHubAddress ? '' : (value.ttsBaseUrl ?? '')
    draft.ttsApiKey = ''
    draft.ttsClearKey = false
    draft.ttsModel = value.ttsModel ?? ''
    draft.ttsVoice = value.ttsVoice ?? ''
    draft.ttsVoiceEn = value.ttsVoiceEn ?? ''
    draft.ttsFormat = value.ttsFormat
    draft.ttsMaxChars = value.ttsMaxChars
  },
  { immediate: true },
)

function keyHint(url: string, clear: boolean, hasKey: boolean | undefined): string {
  if (clear) return 'La clé enregistrée sera oubliée.'
  if (hasKey) return 'Une clé est enregistrée. Elle ne s’affiche jamais : saisissez-en une autre pour la remplacer.'
  if (!url.trim()) return 'Vide : la clé du hub est utilisée. Elle n’est jamais envoyée à une autre adresse.'
  return 'Une autre adresse que celle du hub demande sa propre clé (une valeur quelconque si le service n’en vérifie pas).'
}
const sttKeyHint = computed(() => keyHint(draft.sttBaseUrl, draft.sttClearKey, settings.value?.sttHasKey))
const ttsKeyHint = computed(() => keyHint(draft.ttsBaseUrl, draft.ttsClearKey, settings.value?.ttsHasKey))

async function save() {
  draft.sttMaxBytes = Math.round(maxMib.value * MIB)
  saved.value = await saveVoiceSettings(draft)
  if (saved.value) setTimeout(() => (saved.value = false), 2000)
}

// Teste les réglages enregistrés, pas ceux qu'on est en train de taper : on enregistre d'abord.
async function test(which: 'transcription' | 'speech') {
  testing.value = which
  results[which] = null
  unreachable.value = false
  played.value = null
  const result = await testVoice(which)
  results[which] = result
  unreachable.value = result === null
  testing.value = null
}

async function listen() {
  played.value = await playSpeechSample()
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
      <h1>Voix</h1>
    </div>
    <p class="admin-view__intro">
      La <strong>dictée</strong> (enregistrer un message, obtenir le texte) et la <strong>lecture à voix haute</strong> des
      réponses sont <strong>désactivées par défaut</strong> : le chat utilise alors la dictée et la voix du navigateur. Une fois
      activées, elles passent par un service <strong>compatible OpenAI</strong> : celui du hub (adresse vide), ou un autre —
      un service de l’organisation, ou le pod <code>worker/tts</code> (Kitten TTS) fourni avec Muffin. L’audio et le texte ne
      sont <strong>jamais conservés</strong> par Muffin. Si le service tombe en panne, le chat retombe sur le navigateur.
    </p>

    <p v-if="isLoading && !settings" class="admin-view__empty">Chargement…</p>

    <form v-else-if="settings" class="admin-form" @submit.prevent="save">
      <p v-if="error" class="admin-card__error" role="alert">{{ error }}</p>

      <section class="admin-card" aria-labelledby="voice-stt-title">
        <h2 id="voice-stt-title" class="admin-card__title">Dictée — transcription</h2>
        <p class="admin-card__intro">
          La personne enregistre puis arrête : le texte s’ajoute à son brouillon, modifiable avant l’envoi. L’enregistrement part vers
          le service ci-dessous (<code>POST /audio/transcriptions</code>) ; son contenu est vérifié, jamais décodé par Muffin.
        </p>

        <div class="fr-checkbox-group">
          <input id="stt-enabled" v-model="draft.sttEnabled" type="checkbox" />
          <label class="fr-label" for="stt-enabled">
            Activer la transcription par le serveur
            <span class="fr-hint-text">Il faut un modèle ; sans activation, c’est la dictée du navigateur.</span>
          </label>
        </div>

        <div class="admin-card__field">
          <label for="stt-base-url">Adresse du service</label>
          <input
            id="stt-base-url"
            v-model="draft.sttBaseUrl"
            class="fr-input"
            type="url"
            autocomplete="off"
            :placeholder="settings.hubAvailable ? 'Vide : celle du hub' : 'https://transcription.exemple/v1'"
          />
          <p class="admin-card__hint">
            Une adresse compatible OpenAI, terminée par <code>/v1</code> (vLLM, Speaches, LocalAI, faster-whisper-server…).
            <template v-if="settings.sttUsesHubAddress && settings.sttBaseUrl">Actuellement : {{ settings.sttBaseUrl }}.</template>
          </p>
        </div>

        <div class="admin-card__field">
          <label for="stt-api-key">Clé</label>
          <input id="stt-api-key" v-model="draft.sttApiKey" class="fr-input" type="password" autocomplete="new-password" placeholder="••••••••" />
          <p class="admin-card__hint">{{ sttKeyHint }}</p>
          <div v-if="settings.sttHasKey" class="fr-checkbox-group">
            <input id="stt-clear-key" v-model="draft.sttClearKey" type="checkbox" />
            <label class="fr-label" for="stt-clear-key">Oublier la clé enregistrée</label>
          </div>
        </div>

        <div class="admin-card__row">
          <div class="admin-card__field">
            <label for="stt-model">Modèle</label>
            <input id="stt-model" v-model="draft.sttModel" class="fr-input" type="text" autocomplete="off" placeholder="whisper-1" />
          </div>
          <div class="admin-card__field">
            <label for="stt-language">Langue</label>
            <input id="stt-language" v-model="draft.sttLanguage" class="fr-input" type="text" autocomplete="off" placeholder="auto" />
          </div>
          <div class="admin-card__field">
            <label for="stt-seconds">Durée maximale (s)</label>
            <input id="stt-seconds" v-model.number="draft.sttMaxSeconds" class="fr-input" type="number" min="5" max="3600" />
          </div>
          <div class="admin-card__field">
            <label for="stt-max">Poids maximal (Mo)</label>
            <input id="stt-max" v-model.number="maxMib" class="fr-input" type="number" min="0.1" step="0.5" />
          </div>
        </div>
        <p class="admin-card__hint">
          Langue : <code>auto</code> (le français de l’interface sert d’indice) ou un code comme <code>fr</code>. La durée est celle
          à laquelle l’enregistreur de la page s’arrête ; le poids est la limite stricte côté serveur.
        </p>

        <p class="admin-card__state" :class="{ 'admin-card__state--ready': settings.sttReady }">
          {{ settings.sttReady ? 'Prête : l’enregistreur est proposé dans le chat' : 'Non proposée : dictée du navigateur' }}
        </p>
      </section>

      <section class="admin-card" aria-labelledby="voice-tts-title">
        <h2 id="voice-tts-title" class="admin-card__title">Lecture à voix haute — synthèse</h2>
        <p class="admin-card__intro">
          Le texte d’une réponse est envoyé au service ci-dessous (<code>POST /audio/speech</code>) qui rend l’audio ; la page le
          lit. Pour le <strong>français</strong> avec Kitten TTS, il faut Kitten TTS 2 (les modèles 0.8 n’ont que des voix
          anglaises) : voir <code>docs/voice.md</code> et la licence du modèle.
        </p>

        <div class="fr-checkbox-group">
          <input id="tts-enabled" v-model="draft.ttsEnabled" type="checkbox" />
          <label class="fr-label" for="tts-enabled">
            Activer la lecture par le serveur
            <span class="fr-hint-text">Il faut un modèle ; sans activation, c’est la voix du navigateur.</span>
          </label>
        </div>

        <div class="admin-card__field">
          <label for="tts-base-url">Adresse du service</label>
          <input
            id="tts-base-url"
            v-model="draft.ttsBaseUrl"
            class="fr-input"
            type="url"
            autocomplete="off"
            :placeholder="settings.hubAvailable ? 'Vide : celle du hub' : 'http://worker-tts:8080/v1'"
          />
          <p class="admin-card__hint">
            Une adresse compatible OpenAI, terminée par <code>/v1</code> ; le pod fourni répond sur
            <code>http://worker-tts:8080/v1</code>.
            <template v-if="settings.ttsUsesHubAddress && settings.ttsBaseUrl">Actuellement : {{ settings.ttsBaseUrl }}.</template>
          </p>
        </div>

        <div class="admin-card__field">
          <label for="tts-api-key">Clé</label>
          <input id="tts-api-key" v-model="draft.ttsApiKey" class="fr-input" type="password" autocomplete="new-password" placeholder="••••••••" />
          <p class="admin-card__hint">{{ ttsKeyHint }}</p>
          <div v-if="settings.ttsHasKey" class="fr-checkbox-group">
            <input id="tts-clear-key" v-model="draft.ttsClearKey" type="checkbox" />
            <label class="fr-label" for="tts-clear-key">Oublier la clé enregistrée</label>
          </div>
        </div>

        <div class="admin-card__row">
          <div class="admin-card__field">
            <label for="tts-model">Modèle</label>
            <input id="tts-model" v-model="draft.ttsModel" class="fr-input" type="text" autocomplete="off" placeholder="tts-1 ou kitten-tts-2" />
          </div>
          <div class="admin-card__field">
            <label for="tts-voice">Voix</label>
            <input id="tts-voice" v-model="draft.ttsVoice" class="fr-input" type="text" autocomplete="off" placeholder="French" />
          </div>
          <div class="admin-card__field">
            <label for="tts-voice-en">Voix pour l’anglais (facultatif)</label>
            <input id="tts-voice-en" v-model="draft.ttsVoiceEn" class="fr-input" type="text" autocomplete="off" placeholder="Bella" />
          </div>
        </div>
        <div class="admin-card__row">
          <div class="admin-card__field">
            <label for="tts-format">Format audio</label>
            <select id="tts-format" v-model="draft.ttsFormat" class="fr-select">
              <option v-for="format in FORMATS" :key="format" :value="format">{{ format }}</option>
            </select>
          </div>
          <div class="admin-card__field">
            <label for="tts-chars">Caractères par demande</label>
            <input id="tts-chars" v-model.number="draft.ttsMaxChars" class="fr-input" type="number" min="100" max="100000" />
          </div>
        </div>
        <p class="admin-card__hint">
          Un texte plus long est lu en plusieurs demandes. La voix pour l’anglais sert aux réponses reconnues comme anglaises ;
          sans elle, la voix ci-dessus est utilisée.
        </p>

        <p class="admin-card__state" :class="{ 'admin-card__state--ready': settings.ttsReady }">
          {{ settings.ttsReady ? 'Prête : la lecture passe par le serveur' : 'Non proposée : voix du navigateur' }}
        </p>
      </section>

      <div class="admin-card__footer">
        <span v-if="saved" class="admin-card__saved" role="status">Enregistré</span>
        <button type="submit" class="fr-btn">Enregistrer</button>
      </div>
    </form>

    <div v-if="settings" class="admin-card admin-card--test">
      <h2 class="admin-card__title">Tester</h2>
      <p class="admin-card__intro">
        Essaie les réglages <strong>enregistrés</strong> (enregistrez d’abord). La transcription reçoit une seconde de silence
        générée ici ; la lecture demande une courte phrase. Rien n’est gardé et rien ne compte dans le quota de personne.
      </p>
      <div class="admin-card__buttons">
        <button type="button" class="fr-btn fr-btn--secondary" :disabled="testing !== null" @click="test('transcription')">
          {{ testing === 'transcription' ? 'Essai en cours…' : 'Tester la transcription' }}
        </button>
        <button type="button" class="fr-btn fr-btn--secondary" :disabled="testing !== null" @click="test('speech')">
          {{ testing === 'speech' ? 'Essai en cours…' : 'Tester la lecture' }}
        </button>
        <button v-if="settings.ttsReady" type="button" class="fr-btn fr-btn--tertiary" @click="listen">Écouter un exemple</button>
      </div>

      <p v-if="unreachable" class="admin-card__error" role="alert">Le serveur est inaccessible.</p>
      <p v-if="played === false" class="admin-card__error" role="alert">La lecture n’a pas pu être lancée : vérifiez le test de lecture.</p>
      <template v-for="which in ['transcription', 'speech'] as const" :key="which">
        <div v-if="results[which]" class="admin-card__result" role="status">
          <p v-if="results[which]!.ok" class="admin-card__saved">
            <strong>{{ which === 'transcription' ? 'Transcription' : 'Lecture' }} :</strong>
            {{ results[which]!.message }} ({{ (results[which]!.durationMs / 1000).toFixed(1) }} s<template v-if="results[which]!.contentType">,
            {{ results[which]!.contentType }}, {{ Math.round((results[which]!.audioBytes ?? 0) / 1024) }} Ko</template>).
          </p>
          <p v-else class="admin-card__error">
            <strong>{{ which === 'transcription' ? 'Transcription' : 'Lecture' }} :</strong> {{ results[which]!.message }}
            <span class="admin-card__code">({{ results[which]!.code }}, {{ (results[which]!.durationMs / 1000).toFixed(1) }} s)</span>
          </p>
        </div>
      </template>
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

.admin-form {
  display: flex;
  flex-direction: column;
}

.admin-form > .admin-card__error,
.admin-form > .admin-card__footer {
  max-width: 48rem;
  width: 100%;
  margin: 0 auto 1.5rem;
  box-sizing: border-box;
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

.admin-card__row,
.admin-card__buttons {
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
  margin: 0;
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
</style>

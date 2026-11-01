<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAdminGuardrails } from '../composables/useAdminGuardrails'
import type { Guardrail, GuardrailPolicy, ProbeResult } from '../types/guardrail'
import {
  ENFORCEMENT_LABELS,
  TYPE_LABELS,
  actionLabel,
  describeChanges,
  outcomeLabel,
  totalsByGuardrail,
  verdictLabel,
} from '../utils/guardrails'
import { formatDateTime } from '../utils/routines'
import GuardrailForm from './GuardrailForm.vue'

const { guardrails, policy, stats, audit, isLoading, error, loadGuardrails, loadStats, loadAudit, patch, remove, reorder, savePolicy, probe } =
  useAdminGuardrails()

const editing = ref<Guardrail | null>(null)
const showForm = ref(false)
const notice = ref<string | null>(null)
const days = ref(30)

onMounted(() => {
  void loadGuardrails()
  void loadAudit()
  void loadStats(days.value)
})
watch(days, (value) => void loadStats(value))

// Par étape : c'est l'ordre dans lequel ils s'exécutent.
const stages = computed(() => {
  const byStage = new Map<number, Guardrail[]>()
  for (const guardrail of guardrails.value) byStage.set(guardrail.stage, [...(byStage.get(guardrail.stage) ?? []), guardrail])
  return [...byStage.entries()].sort(([a], [b]) => a - b)
})
const totals = computed(() => totalsByGuardrail(stats.value?.rows ?? []))
const blockRate = computed(() =>
  stats.value && stats.value.requestsChecked ? Math.round((stats.value.requestsBlocked / stats.value.requestsChecked) * 1000) / 10 : 0,
)

function startCreate() {
  editing.value = null
  showForm.value = true
}

function startEdit(guardrail: Guardrail) {
  editing.value = guardrail
  showForm.value = true
}

function saved() {
  showForm.value = false
  void loadStats(days.value)
}

async function setEnabled(guardrail: Guardrail, enabled: boolean) {
  notice.value = await patch(guardrail.id, { enabled })
}

async function setEnforcement(guardrail: Guardrail, enforcement: string) {
  notice.value = await patch(guardrail.id, { enforcement })
}

async function destroy(guardrail: Guardrail) {
  if (!window.confirm(`Supprimer le garde-fou « ${guardrail.name} » ? Son historique de réglages est gardé dans le journal.`)) return
  notice.value = await remove(guardrail.id)
}

// Monte ou descend dans son étape : l'ordre envoyé est celui de tous les garde-fous.
async function move(guardrail: Guardrail, step: -1 | 1) {
  const ids = guardrails.value.map((item) => item.id)
  const same = guardrails.value.filter((item) => item.stage === guardrail.stage).map((item) => item.id)
  const target = same[same.indexOf(guardrail.id) + step]
  if (!target) return
  const from = ids.indexOf(guardrail.id)
  const to = ids.indexOf(target)
  ids[from] = target
  ids[to] = guardrail.id
  notice.value = await reorder(ids)
}

// --- la politique d'ensemble ---
const policyDraft = reactive<GuardrailPolicy>({
  aggregation: 'any',
  quorum: 2,
  waitStrategy: 'wait_all',
  timeoutMs: 2000,
  onIncomplete: 'continue',
  minVerdicts: 0,
  showCategory: false,
  defaultRefusal: '',
})
const policyMessage = ref<string | null>(null)
const policySaved = ref(false)
watch(policy, (value) => value && Object.assign(policyDraft, value), { immediate: true })

async function savePolicyDraft() {
  policyMessage.value = await savePolicy(policyDraft)
  policySaved.value = policyMessage.value === null
  if (policySaved.value) setTimeout(() => (policySaved.value = false), 2000)
}

// --- essayer un texte ---
const sample = ref('')
const probing = ref(false)
const probeResult = ref<ProbeResult | null>(null)
const probeMessage = ref<string | null>(null)

async function tryText() {
  probing.value = true
  probeResult.value = null
  const { result, message } = await probe(sample.value)
  probeResult.value = result
  probeMessage.value = message
  probing.value = false
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
      <h1>Garde-fous d’entrée</h1>
      <button type="button" class="fr-btn" :disabled="showForm" @click="startCreate">Nouveau garde-fou</button>
    </div>
    <p class="admin-view__intro">
      Des vérifications faites <strong>avant que la demande n’aille à un modèle</strong>, définies par vous seul. Une demande
      bloquée ne déclenche aucun appel de modèle, aucune recherche, aucun appel au web. Pour mesurer les faux positifs, créez un
      garde-fou en mode <em>Observer</em>, regardez les déclenchements, puis passez-le en <em>Bloquer</em> sans redéploiement.
      <strong>Ce n’est pas une garantie</strong> : les règles sont déterministes, un juge à base de modèle peut être contourné.
    </p>

    <p v-if="error" class="admin-view__error" role="alert">{{ error }}</p>
    <p v-if="notice" class="admin-view__error" role="alert">{{ notice }}</p>

    <GuardrailForm v-if="showForm" :guardrail="editing" @saved="saved" @cancel="showForm = false" />

    <p v-if="isLoading && !guardrails.length" class="admin-view__empty">Chargement…</p>

    <div v-for="[stage, list] in stages" :key="stage" class="admin-card">
      <h2 class="admin-card__title">
        Étape {{ stage }}
        <span class="admin-card__muted">{{ stage === 1 ? '— part en premier, ensemble' : '— seulement si l’étape précédente a laissé passer' }}</span>
      </h2>
      <ul class="guardrail-list">
        <li v-for="guardrail in list" :key="guardrail.id" class="guardrail-row">
          <div class="guardrail-row__main">
            <div class="fr-toggle">
              <input :id="`on-${guardrail.id}`" type="checkbox" class="fr-toggle__input" :checked="guardrail.enabled" @change="setEnabled(guardrail, ($event.target as HTMLInputElement).checked)" />
              <label class="fr-toggle__label" :for="`on-${guardrail.id}`" data-fr-checked-label="Activé" data-fr-unchecked-label="Désactivé">
                {{ guardrail.name }}
              </label>
            </div>
            <p class="guardrail-row__meta">
              {{ TYPE_LABELS[guardrail.type] }} · version {{ guardrail.version }}
              <span v-if="guardrail.presetKey"> · fourni avec l’application</span>
              <span v-if="guardrail.scopeGroups.length || guardrail.scopeAssistants.length"> · limité</span>
              <span v-if="guardrail.critical"> · critique</span>
            </p>
            <p v-if="guardrail.description" class="guardrail-row__description">{{ guardrail.description }}</p>
          </div>
          <div class="guardrail-row__controls">
            <label class="fr-sr-only" :for="`mode-${guardrail.id}`">Mode de {{ guardrail.name }}</label>
            <select :id="`mode-${guardrail.id}`" class="fr-select guardrail-row__mode" :value="guardrail.enforcement" @change="setEnforcement(guardrail, ($event.target as HTMLSelectElement).value)">
              <option v-for="(label, mode) in ENFORCEMENT_LABELS" :key="mode" :value="mode" :disabled="mode === 'redact' && guardrail.type === 'llm'">{{ label }}</option>
            </select>
            <button type="button" class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm" :aria-label="`Monter ${guardrail.name}`" @click="move(guardrail, -1)">↑</button>
            <button type="button" class="fr-btn fr-btn--tertiary-no-outline fr-btn--sm" :aria-label="`Descendre ${guardrail.name}`" @click="move(guardrail, 1)">↓</button>
            <button type="button" class="fr-btn fr-btn--secondary fr-btn--sm" @click="startEdit(guardrail)">Modifier</button>
            <button type="button" class="fr-btn fr-btn--tertiary fr-btn--sm" @click="destroy(guardrail)">Supprimer</button>
          </div>
        </li>
      </ul>
    </div>

    <form v-if="policy" class="admin-card" @submit.prevent="savePolicyDraft">
      <h2 class="admin-card__title">Politique d’ensemble</h2>
      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="p-aggregation">Qui arrête la demande</label>
          <select id="p-aggregation" v-model="policyDraft.aggregation" class="fr-select">
            <option value="any">Un seul garde-fou bloquant qui signale suffit</option>
            <option value="quorum">Au moins N garde-fous bloquants signalent</option>
          </select>
        </div>
        <div v-if="policyDraft.aggregation === 'quorum'" class="admin-card__field">
          <label for="p-quorum">N</label>
          <input id="p-quorum" v-model.number="policyDraft.quorum" class="fr-input" type="number" min="1" />
        </div>
        <div class="admin-card__field">
          <label for="p-wait">Attente des verdicts</label>
          <select id="p-wait" v-model="policyDraft.waitStrategy" class="fr-select">
            <option value="wait_all">Attendre tous les verdicts (tout est enregistré)</option>
            <option value="first_block">Arrêter les autres dès qu’un blocage est acquis</option>
          </select>
        </div>
      </div>
      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="p-timeout">Délai global (ms)</label>
          <input id="p-timeout" v-model.number="policyDraft.timeoutMs" class="fr-input" type="number" min="50" step="100" />
        </div>
        <div class="admin-card__field">
          <label for="p-min">Verdicts bloquants exigés</label>
          <input id="p-min" v-model.number="policyDraft.minVerdicts" class="fr-input" type="number" min="0" />
        </div>
        <div class="admin-card__field">
          <label for="p-incomplete">Si trop peu ont répondu</label>
          <select id="p-incomplete" v-model="policyDraft.onIncomplete" class="fr-select">
            <option value="continue">Laisser continuer</option>
            <option value="block">Bloquer</option>
          </select>
        </div>
      </div>
      <div class="admin-card__field">
        <label for="p-refusal">Message de refus par défaut</label>
        <textarea id="p-refusal" v-model="policyDraft.defaultRefusal" class="fr-input" rows="2" maxlength="1000" />
      </div>
      <div class="fr-checkbox-group">
        <input id="p-category" v-model="policyDraft.showCategory" type="checkbox" />
        <label class="fr-label" for="p-category">
          Nommer la catégorie générale dans le refus (« données personnelles »)
          <span class="fr-hint-text">Décoché : le refus est totalement neutre.</span>
        </label>
      </div>
      <div class="admin-card__footer">
        <span v-if="policySaved" class="admin-card__saved" role="status">Enregistré</span>
        <span v-if="policyMessage" class="admin-card__error" role="alert">{{ policyMessage }}</span>
        <button type="submit" class="fr-btn">Enregistrer</button>
      </div>
    </form>

    <div v-if="policy" class="admin-card">
      <h2 class="admin-card__title">Essayer un texte</h2>
      <p class="admin-card__intro">
        Dit ce que chaque garde-fou — même éteint — répond à un texte, et ce que la politique ferait des garde-fous activés.
        Aucun run n’est créé ; <strong>le texte n’est gardé nulle part</strong>.
      </p>
      <div class="admin-card__field">
        <label for="probe-text">Texte</label>
        <textarea id="probe-text" v-model="sample" class="fr-input" rows="3" maxlength="20000" />
      </div>
      <div><button type="button" class="fr-btn fr-btn--secondary" :disabled="probing || !sample.trim()" @click="tryText">{{ probing ? 'Vérification…' : 'Essayer' }}</button></div>
      <p v-if="probeMessage" class="admin-card__error" role="alert">{{ probeMessage }}</p>
      <div v-if="probeResult" role="status" class="admin-table">
        <p>
          <strong>{{ outcomeLabel(probeResult.outcome) }}</strong>
          <span v-if="probeResult.incomplete"> (verdicts incomplets)</span>
          <span v-if="probeResult.message"> — « {{ probeResult.message }} »</span>
        </p>
        <p v-if="probeResult.outcome === 'continue_with_redaction'">Texte envoyé au modèle : <code>{{ probeResult.text }}</code></p>
        <table>
          <caption class="fr-sr-only">Verdict de chaque garde-fou</caption>
          <thead><tr><th scope="col">Garde-fou</th><th scope="col">Verdict</th><th scope="col">Catégorie</th><th scope="col">Score</th><th scope="col">Temps</th><th scope="col">Effet</th></tr></thead>
          <tbody>
            <tr v-for="item in probeResult.verdicts" :key="item.guardrailId ?? item.name">
              <td>{{ item.name }} <span v-if="!item.enabled" class="admin-table__muted">(éteint)</span></td>
              <td>{{ verdictLabel(item.verdict) }}</td>
              <td>{{ item.category ?? '—' }}</td>
              <td>{{ item.score === null ? '—' : item.score.toFixed(2) }}</td>
              <td>{{ item.latencyMs }} ms</td>
              <td>{{ actionLabel(item.action) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="policy" class="admin-card">
      <h2 class="admin-card__title">Ce qu’ils ont fait</h2>
      <div class="admin-card__row">
        <div class="admin-card__field">
          <label for="stats-days">Période</label>
          <select id="stats-days" v-model.number="days" class="fr-select">
            <option :value="7">7 jours</option>
            <option :value="30">30 jours</option>
            <option :value="90">90 jours</option>
          </select>
        </div>
      </div>
      <p v-if="stats" class="admin-card__intro">
        {{ stats.requestsChecked.toLocaleString('fr-FR') }} demande(s) vérifiée(s), {{ stats.requestsBlocked.toLocaleString('fr-FR') }} bloquée(s)
        ({{ blockRate }} %). Des comptes et des temps : jamais le texte des demandes.
      </p>
      <p v-if="!totals.length" class="admin-card__intro">Aucun déclenchement sur la période.</p>
      <div v-else class="admin-table">
        <table>
          <caption class="fr-sr-only">Déclenchements par garde-fou</caption>
          <thead><tr><th scope="col">Garde-fou</th><th scope="col">Vérifications</th><th scope="col">Signalées</th><th scope="col">Bloquées</th><th scope="col">Taux de blocage</th><th scope="col">En panne</th><th scope="col">Temps moyen</th></tr></thead>
          <tbody>
            <tr v-for="row in totals" :key="row.name">
              <td>{{ row.name }}</td>
              <td>{{ row.evaluated }}</td>
              <td>{{ row.flagged }}</td>
              <td>{{ row.blocked }}</td>
              <td>{{ Math.round(row.blockRate * 1000) / 10 }} %</td>
              <td>{{ row.failed }}</td>
              <td>{{ row.avgLatencyMs }} ms</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="policy" class="admin-card">
      <h2 class="admin-card__title">Journal des modifications</h2>
      <p class="admin-card__intro">Toute modification change le comportement de l’application pour tout le monde : elle est gardée, avec qui et quand.</p>
      <p v-if="!audit.length" class="admin-card__intro">Aucune modification.</p>
      <div v-else class="admin-table">
        <table>
          <caption class="fr-sr-only">Modifications des garde-fous</caption>
          <thead><tr><th scope="col">Quand</th><th scope="col">Qui</th><th scope="col">Garde-fou</th><th scope="col">Quoi</th></tr></thead>
          <tbody>
            <tr v-for="entry in audit" :key="entry.id">
              <td>{{ formatDateTime(entry.createdAt) }}</td>
              <td>{{ entry.userDisplay }}</td>
              <td>{{ entry.guardrailName || 'Politique' }}</td>
              <td>{{ describeChanges(entry).join(' ; ') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
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
  max-width: 56rem;
  margin: 0 auto 1rem;
  color: var(--text-mention-grey);
  text-decoration: none;
  font-size: 0.875rem;
}

.admin-view__header,
.admin-view__intro {
  max-width: 56rem;
  margin-left: auto;
  margin-right: auto;
}

.admin-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
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
  max-width: 56rem;
  margin: 1rem auto;
  color: var(--text-mention-grey);
}

.admin-view__error {
  color: var(--text-default-error);
}

.admin-card {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 56rem;
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

.admin-card__muted,
.admin-table__muted {
  font-size: 0.8125rem;
  font-weight: 400;
  color: var(--text-mention-grey);
}

.admin-card__intro {
  margin: 0;
  color: var(--text-mention-grey);
  font-size: 0.875rem;
}

.admin-card__row {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
}

.admin-card__field {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 0.375rem;
  min-width: 11rem;
}

.admin-card__field label {
  font-size: 0.875rem;
  font-weight: 700;
}

.admin-card__footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 0.75rem;
}

.admin-card__saved {
  margin-right: auto;
  font-size: 0.875rem;
  color: var(--text-default-success);
}

.admin-card__error {
  margin: 0;
  font-size: 0.875rem;
  color: var(--text-default-error);
}

.guardrail-list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.guardrail-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border-default-grey);
}

.guardrail-row__main {
  flex: 1;
  min-width: 14rem;
}

.guardrail-row__meta,
.guardrail-row__description {
  margin: 0.25rem 0 0;
  font-size: 0.8125rem;
  color: var(--text-mention-grey);
}

.guardrail-row__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.375rem;
}

.guardrail-row__mode {
  width: 9rem;
}

.admin-table {
  overflow-x: auto;
}

.admin-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8125rem;
}

.admin-table th,
.admin-table td {
  padding: 0.375rem 0.5rem;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--border-default-grey);
}
</style>

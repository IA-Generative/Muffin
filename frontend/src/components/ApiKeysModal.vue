<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useApiKeys } from '../composables/useApiKeys'
import { type ApiKey, apiKeyStatus, daysLeft, scopeLabel } from '../utils/apiKeys'

defineEmits<{
  close: []
}>()

const { keys, loading, error, created, load, create, revoke, dismissCreated } = useApiKeys()

// What can be asked of a key today: more come with the API compatible with OpenAI (#513).
const AVAILABLE_SCOPES = ['search']
const EXPIRY_CHOICES = [
  { days: 7, label: '7 jours' },
  { days: 30, label: '30 jours' },
  { days: 90, label: '90 jours' },
  { days: 180, label: '180 jours' },
  { days: 365, label: '1 an' },
]

const name = ref('')
const days = ref(90)
const copied = ref(false)
const creating = ref(false)

onMounted(load)

async function submit() {
  const trimmed = name.value.trim()
  if (!trimmed || creating.value) return
  creating.value = true
  try {
    if (await create(trimmed, AVAILABLE_SCOPES, days.value)) name.value = ''
  } finally {
    creating.value = false
  }
}

async function copyKey() {
  if (!created.value) return
  try {
    await navigator.clipboard.writeText(created.value.key)
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    // The key stays selectable on the screen.
  }
}

function confirmRevoke(key: ApiKey) {
  if (window.confirm(`Révoquer la clé « ${key.name} » ? Les outils qui l'utilisent cesseront de fonctionner.`)) {
    void revoke(key.id)
  }
}

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' }) : '—'
}

const STATUS_LABELS = { active: 'Active', revoked: 'Révoquée', expired: 'Expirée' }
</script>

<template>
  <div class="keys-overlay" @click.self="$emit('close')">
    <div class="keys-modal" role="dialog" aria-modal="true" aria-labelledby="keys-title">
      <div class="keys-modal__header">
        <h2 id="keys-title">Clés d'API</h2>
        <button type="button" class="keys-modal__close" aria-label="Fermer" @click="$emit('close')">✕</button>
      </div>

      <p class="keys-modal__intro">
        Une clé permet à un script ou à un outil d'agir en votre nom, avec vos droits, sans que vous soyez connecté. Elle expire,
        se révoque à tout moment, et n'est affichée qu'une seule fois.
      </p>

      <div v-if="created" class="keys-modal__created" role="status">
        <p class="keys-modal__created-title">Votre clé « {{ created.name }} »</p>
        <div class="keys-modal__secret">
          <code data-testid="new-key">{{ created.key }}</code>
          <button type="button" class="keys-modal__button" @click="copyKey">{{ copied ? 'Copiée' : 'Copier' }}</button>
        </div>
        <p class="keys-modal__warning">
          Copiez-la maintenant et gardez-la comme un mot de passe : elle ne pourra plus être affichée. Si vous la perdez, révoquez-la et
          créez-en une autre.
        </p>
        <button type="button" class="keys-modal__button keys-modal__button--primary" @click="dismissCreated">
          J'ai copié ma clé
        </button>
      </div>

      <form v-else class="keys-modal__form" @submit.prevent="submit">
        <label class="keys-modal__label" for="key-name">Nom de la clé</label>
        <input id="key-name" v-model="name" type="text" maxlength="100" placeholder="Mon script, mon assistant…" required />
        <div class="keys-modal__row">
          <label class="keys-modal__label" for="key-days">Valable</label>
          <select id="key-days" v-model.number="days">
            <option v-for="choice in EXPIRY_CHOICES" :key="choice.days" :value="choice.days">{{ choice.label }}</option>
          </select>
          <button type="submit" class="keys-modal__button keys-modal__button--primary" :disabled="!name.trim() || creating">
            Créer la clé
          </button>
        </div>
        <p class="keys-modal__hint">Autorise : {{ AVAILABLE_SCOPES.map(scopeLabel).join(', ') }}.</p>
      </form>

      <p v-if="error" class="keys-modal__error" role="alert">{{ error }}</p>

      <h3 class="keys-modal__subtitle">Mes clés</h3>
      <p v-if="loading && !keys.length" class="keys-modal__hint">Chargement…</p>
      <p v-else-if="!keys.length" class="keys-modal__hint">Vous n'avez pas encore de clé.</p>
      <ul v-else class="keys-modal__list">
        <li
          v-for="key in keys"
          :key="key.id"
          class="keys-modal__item"
          :class="{ 'keys-modal__item--inactive': apiKeyStatus(key) !== 'active' }"
        >
          <div class="keys-modal__item-main">
            <span class="keys-modal__item-name">{{ key.name }}</span>
            <code class="keys-modal__item-prefix">{{ key.key_prefix }}…</code>
            <span class="keys-modal__badge" :class="`keys-modal__badge--${apiKeyStatus(key)}`">
              {{ STATUS_LABELS[apiKeyStatus(key)] }}
            </span>
          </div>
          <div class="keys-modal__item-meta">
            {{ key.scopes.map(scopeLabel).join(', ') }} · créée le {{ formatDate(key.created_at) }} ·
            <template v-if="apiKeyStatus(key) === 'active'">expire dans {{ daysLeft(key) }} j</template>
            <template v-else-if="apiKeyStatus(key) === 'revoked'">révoquée le {{ formatDate(key.revoked_at) }}</template>
            <template v-else>expirée le {{ formatDate(key.expires_at) }}</template>
            · {{ key.last_used_at ? `utilisée le ${formatDate(key.last_used_at)}` : 'jamais utilisée' }}
          </div>
          <button
            v-if="apiKeyStatus(key) === 'active'"
            type="button"
            class="keys-modal__button keys-modal__button--danger"
            :aria-label="`Révoquer la clé ${key.name}`"
            @click="confirmRevoke(key)"
          >
            Révoquer
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.keys-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

.keys-modal {
  width: 100%;
  max-width: 38rem;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  border-radius: 0.5rem;
  padding: 1.5rem;
  box-sizing: border-box;
}

.keys-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.keys-modal__header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.keys-modal__close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-mention-grey);
}

.keys-modal__intro,
.keys-modal__hint {
  font-size: 0.875rem;
  color: var(--text-mention-grey);
}

.keys-modal__form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin: 1rem 0;
}

.keys-modal__form input,
.keys-modal__form select {
  padding: 0.5rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  font: inherit;
}

.keys-modal__row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.keys-modal__label {
  font-size: 0.875rem;
  font-weight: 600;
}

.keys-modal__button {
  padding: 0.5rem 0.875rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  color: var(--text-default-grey);
  cursor: pointer;
  font: inherit;
}

.keys-modal__button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.keys-modal__button--primary {
  margin-left: auto;
  border-color: var(--border-action-high-blue-france);
  background: var(--background-action-high-blue-france);
  color: var(--text-inverted-blue-france);
}

.keys-modal__button--danger {
  color: var(--text-default-error);
  border-color: var(--border-plain-error);
}

.keys-modal__created {
  margin: 1rem 0;
  padding: 1rem;
  border: 1px solid var(--border-default-success);
  border-radius: 0.5rem;
  background: var(--background-contrast-success);
}

.keys-modal__created-title {
  margin: 0 0 0.5rem;
  font-weight: 700;
}

.keys-modal__secret {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.keys-modal__secret code {
  flex: 1;
  min-width: 0;
  padding: 0.5rem;
  overflow-wrap: anywhere;
  border-radius: 0.25rem;
  background: var(--background-default-grey);
  user-select: all;
}

.keys-modal__warning {
  font-size: 0.875rem;
}

.keys-modal__error {
  color: var(--text-default-error);
  font-size: 0.875rem;
}

.keys-modal__subtitle {
  margin: 1.25rem 0 0.5rem;
  font-size: 1rem;
}

.keys-modal__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.keys-modal__item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.25rem 0.75rem;
  align-items: center;
  padding: 0.75rem;
  border: 1px solid var(--border-default-grey);
  border-radius: 0.5rem;
}

.keys-modal__item--inactive {
  opacity: 0.65;
}

.keys-modal__item-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.keys-modal__item-name {
  font-weight: 600;
}

.keys-modal__item-meta {
  grid-column: 1;
  font-size: 0.75rem;
  color: var(--text-mention-grey);
}

.keys-modal__item .keys-modal__button {
  grid-column: 2;
  grid-row: 1 / span 2;
}

.keys-modal__badge {
  padding: 0 0.5rem;
  border-radius: 0.75rem;
  font-size: 0.75rem;
  background: var(--background-alt-grey);
}

.keys-modal__badge--active {
  background: var(--background-contrast-success);
  color: var(--text-default-success);
}
</style>

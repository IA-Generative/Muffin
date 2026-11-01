import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  describeSchedule,
  emptyDraft,
  runStatusLabel,
  scheduleProblem,
  shortTime,
  skipReasonLabel,
  stateLabel,
} from './routines.ts'

const base = { timezone: 'Europe/Paris', intervalMinutes: null, timeOfDay: null, weekdays: null, dayOfMonth: null }

test('le rythme se dit comme la personne le dirait', () => {
  assert.equal(describeSchedule({ ...base, kind: 'daily', timeOfDay: '09:00:00' }), 'Tous les jours à 09 h 00')
  assert.equal(
    describeSchedule({ ...base, kind: 'weekly', timeOfDay: '08:30', weekdays: [3, 0] }),
    'Le lundi et le jeudi à 08 h 30',
  )
  assert.equal(describeSchedule({ ...base, kind: 'weekly', timeOfDay: '08:30', weekdays: [0] }), 'Le lundi à 08 h 30')
  assert.equal(describeSchedule({ ...base, kind: 'monthly', timeOfDay: '07:00', dayOfMonth: 1 }), 'Le 1er de chaque mois à 07 h 00')
  assert.equal(describeSchedule({ ...base, kind: 'monthly', timeOfDay: '07:00', dayOfMonth: 31 }), 'Le 31 de chaque mois à 07 h 00')
})

test('un intervalle se dit en heures ou en jours quand il tombe juste', () => {
  const at = (intervalMinutes: number) => describeSchedule({ ...base, kind: 'interval', intervalMinutes })
  assert.equal(at(60), 'Toutes les heures')
  assert.equal(at(120), 'Toutes les 2 heures')
  assert.equal(at(1440), 'Tous les jours')
  assert.equal(at(2880), 'Tous les 2 jours')
  assert.equal(at(90), 'Toutes les 90 minutes')
})

test('le formulaire repère ce qui manque avant le serveur, et le serveur reste juge', () => {
  assert.equal(scheduleProblem({ ...base, kind: 'interval' }, 60), 'Indiquez l’intervalle.')
  assert.match(scheduleProblem({ ...base, kind: 'interval', intervalMinutes: 30 }, 60) ?? '', /60 minutes/)
  assert.equal(scheduleProblem({ ...base, kind: 'interval', intervalMinutes: 60 }, 60), null)
  assert.equal(scheduleProblem({ ...base, kind: 'daily' }, 60), 'Indiquez l’heure.')
  assert.equal(scheduleProblem({ ...base, kind: 'weekly', timeOfDay: '09:00', weekdays: [] }, 60), 'Choisissez au moins un jour.')
  assert.equal(scheduleProblem({ ...base, kind: 'monthly', timeOfDay: '09:00' }, 60), 'Indiquez le jour du mois.')
  assert.equal(scheduleProblem({ ...base, kind: 'daily', timeOfDay: '09:00' }, 60), null)
})

test('une exécution sautée dit pourquoi, une autre dit seulement son état', () => {
  assert.equal(runStatusLabel('skipped', 'no_new_documents'), 'Aucun nouveau document')
  assert.equal(skipReasonLabel('quelque_chose_de_neuf'), 'Sautée')
  assert.equal(runStatusLabel('succeeded'), 'Réussie')
  assert.equal(runStatusLabel('running'), 'En cours')
})

test('une routine suspendue dit par qui ou pourquoi', () => {
  assert.equal(stateLabel('active'), 'Active')
  assert.equal(stateLabel('paused'), 'En pause')
  assert.equal(stateLabel('suspended', 'failures'), 'Suspendue après des échecs répétés')
  assert.equal(stateLabel('suspended', 'admin'), 'Suspendue par un administrateur')
})

test('un nouveau brouillon part d’un rythme hebdomadaire, sans collection ni recherche sur le web', () => {
  const draft = emptyDraft()
  assert.equal(draft.schedule.kind, 'weekly')
  assert.deepEqual([draft.collectionIds, draft.webSearch, draft.condition, draft.notify], [[], false, 'always', 'always'])
  assert.equal(shortTime('09:00:00'), '09:00')
  assert.equal(shortTime(null), '')
})

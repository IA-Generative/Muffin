import assert from 'node:assert/strict'
import { test } from 'node:test'
import { applyEvents, describeEvent, describePlan, type RunEvent } from './runSteps.ts'

const event = (type: string, data: Record<string, unknown> | null = null, taskId: string | null = null): RunEvent => ({
  id: `${type}-${Math.random()}`,
  type,
  taskId,
  data,
  createdAt: '2026-10-31T10:00:00Z',
})

test('a step that starts runs, and the event that completes it updates the same line', () => {
  const started = applyEvents([], [event('query_analysis_started')])
  assert.deepEqual(started.map((step) => [step.label, step.state]), [['Analyse de la question', 'running']])

  const done = applyEvents(started, [
    event('query_analysis_completed', { analysis: { mode: 'search', queries: [{ query: 'congés' }], collections: ['a', 'b'] } }),
  ])
  assert.equal(done.length, 1)
  assert.equal(done[0].state, 'done')
  assert.equal(done[0].detail, '1 recherche · 2 collections choisies')
})

test('the plan says what it decided, in one line', () => {
  assert.equal(describePlan({ mode: 'direct' }), 'Réponse directe, sans consulter vos documents')
  assert.equal(describePlan({ mode: 'search', queries: [{ query: 'a' }, { query: 'b' }], collections: [] }), '2 recherches · toutes vos collections')
  assert.equal(describePlan({ mode: 'clarify' }), 'Une précision est nécessaire')
  assert.equal(describePlan(undefined), undefined)
})

test('each parallel search has its own line, with where it looked and what it found', () => {
  const steps = applyEvents(
    [],
    [
      event('task_started', { query: 'congés des cadres', tool: 'search' }, 'task-1'),
      event('task_started', { query: 'congés des agents', tool: 'search' }, 'task-2'),
      event('vdb_routing_completed', { selected: ['Procédures RH', 'Support IT'] }, 'task-1'),
      event('task_completed', { evidence_count: 7 }, 'task-1'),
    ],
  )

  const first = steps.find((step) => step.key === 'task:task-1')!
  assert.equal(first.label, 'Recherche : « congés des cadres »')
  assert.equal(first.detail, '7 passages trouvés')
  assert.equal(first.state, 'done')
  assert.equal(steps.find((step) => step.key === 'task:task-2')!.state, 'running')
  assert.equal(steps.find((step) => step.key === 'task:task-1:where')!.label, 'Dans Procédures RH, Support IT')
})

test('a failed search is shown as failed, with the label it had', () => {
  const steps = applyEvents([], [event('task_started', { query: 'x' }, 't'), event('task_failed', { error: 'boom' }, 't')])

  assert.equal(steps[0].state, 'failed')
  assert.equal(steps[0].label, 'Recherche : « x »')
  assert.equal(steps[0].detail, 'La recherche a échoué')
})

test('the gate says whether the results suffice, and a widening is a step of its own', () => {
  assert.equal(describeEvent(event('coverage_evaluation_completed', { status: 'insufficient' }))!.detail, 'Peu de résultats')
  assert.equal(describeEvent(event('coverage_evaluation_completed', { status: 'sufficient' }))!.detail, 'Suffisants pour répondre')
  assert.equal(describeEvent(event('search_widened'))!.label, 'Recherche élargie à toutes vos collections')
})

test('the answer says how many sources it cites, only when it cites some', () => {
  assert.equal(describeEvent(event('answer_generation_completed', { citation_count: 3 }))!.detail, '3 sources citées')
  assert.equal(describeEvent(event('answer_generation_completed', { citation_count: 0 }))!.detail, undefined)
})

test('the images read for the answer are said, and so is a model that was changed for them', () => {
  const reading = describeEvent(event('image_reading_started', { count: 2 }))!
  assert.equal(reading.label, 'Lecture des images jointes')
  assert.equal(reading.detail, '2 images')
  const switched = describeEvent(event('answer_model_switched', { from: 'a', to: 'vision-1', reason: 'images' }))!
  assert.equal(switched.label, 'Réponse écrite par un modèle qui lit les images')
  assert.equal(switched.detail, 'vision-1')
})

test('an event that adds nothing for the user makes no line, and the list given is never changed', () => {
  assert.equal(describeEvent(event('something_internal')), undefined)
  const before = applyEvents([], [event('run_started')])
  const after = applyEvents(before, [event('answer_generation_started')])

  assert.equal(before.length, 1)
  assert.equal(after.length, 2)
})

test('a long question is cut so that the line stays readable', () => {
  const steps = applyEvents([], [event('task_started', { query: 'x'.repeat(200) }, 't')])

  assert.ok(steps[0].label.length < 100)
  assert.ok(steps[0].label.includes('…'))
})

test('a command on the memory is a step that says what came of it and nothing of what was said', () => {
  const steps = applyEvents([], [event('memory_command_completed', { action: 'remember', outcome: 'saved' })])
  const refused = applyEvents([], [event('memory_command_completed', { action: 'remember', outcome: 'refused' })])

  assert.deepEqual(steps.map((step) => [step.label, step.detail, step.state]), [['Votre mémoire', 'retenu', 'done']])
  assert.equal(refused[0].detail, 'non modifiée')
})

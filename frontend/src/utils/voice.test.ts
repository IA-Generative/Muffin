import assert from 'node:assert/strict'
import { test } from 'node:test'
import { chunkForSpeech, dictationNotice, engineIsDown, formatClock, guessLanguage, pickRecorderType, speechNotice } from './voice.ts'

test('le premier format que le navigateur sait enregistrer est choisi, et aucun si aucun ne l’est', () => {
  assert.equal(pickRecorderType(() => true), 'audio/webm;codecs=opus')
  assert.equal(pickRecorderType((type) => type === 'audio/mp4'), 'audio/mp4')
  assert.equal(pickRecorderType(() => false), undefined)
})

test('la durée écoulée s’écrit minutes:secondes', () => {
  assert.equal(formatClock(0), '0:00')
  assert.equal(formatClock(7.9), '0:07')
  assert.equal(formatClock(723), '12:03')
  assert.equal(formatClock(-4), '0:00')
})

test('la langue d’une réponse est devinée entre le français et l’anglais, et laissée de côté quand on ne peut pas trancher', () => {
  assert.equal(guessLanguage('Les congés payés sont de cinq semaines pour les agents de la collectivité.'), 'fr')
  assert.equal(guessLanguage('The leave is five weeks for the agents of the department and it can be split.'), 'en')
  assert.equal(guessLanguage('Oui.'), undefined)
  assert.equal(guessLanguage('Bonjour'), undefined)
  assert.equal(guessLanguage('1234 5678 9012'), undefined)
})

test('chaque moteur dit où part la voix', () => {
  assert.match(dictationNotice('hub'), /service de modèles/)
  assert.match(dictationNotice('service'), /service de transcription/)
  assert.match(dictationNotice('browser'), /navigateur/)
  assert.match(speechNotice('hub'), /service de modèles/)
  assert.match(speechNotice('browser'), /navigateur/)
})

test('un moteur qui ne marche pas fait retomber sur le navigateur, un enregistrement refusé non', () => {
  for (const status of [404, 500, 502, 503, 504]) assert.equal(engineIsDown(status), true)
  for (const status of [413, 415, 422, 429]) assert.equal(engineIsDown(status), false)
})

test('un texte court est lu d’un trait, un texte vide ne l’est pas', () => {
  assert.deepEqual(chunkForSpeech('  Bonjour   à tous. ', 100), ['Bonjour à tous.'])
  assert.deepEqual(chunkForSpeech('   ', 100), [])
})

test('un long texte est coupé à la fin des phrases, sans jamais dépasser le maximum ni rien perdre', () => {
  const text = 'Première phrase du texte. Deuxième phrase un peu plus longue. Troisième ! Quatrième ? Cinquième…'
  const chunks = chunkForSpeech(text, 40)

  assert.ok(chunks.length > 1)
  assert.ok(chunks.every((chunk) => chunk.length <= 40))
  assert.equal(chunks.join(' '), text)
  assert.ok(chunks[0].endsWith('.'))
})

test('une phrase plus longue que le maximum est coupée entre deux mots, et un mot trop long net', () => {
  const sentence = 'un deux trois quatre cinq six sept huit neuf dix'
  const chunks = chunkForSpeech(sentence, 15)

  assert.ok(chunks.every((chunk) => chunk.length <= 15))
  assert.equal(chunks.join(' '), sentence)
  const long = chunkForSpeech(`début ${'x'.repeat(25)} fin`, 10)
  assert.ok(long.every((chunk) => chunk.length <= 10))
  assert.equal(long.join('').replace(/ /g, ''), `début${'x'.repeat(25)}fin`)
})

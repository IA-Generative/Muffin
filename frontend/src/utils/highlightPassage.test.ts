import assert from 'node:assert/strict'
import { test } from 'node:test'
import { highlightPassage, highlightRange, highlightRanges } from './highlightPassage.ts'

const marked = (content: string, passage: string | null | undefined) =>
  highlightPassage(content, passage)
    .segments.filter((segment) => segment.highlighted)
    .map((segment) => segment.text)

const PAGE = 'Article 1\nLe locataire paie son loyer\nchaque mois.\n\nArticle 2\nLe bail dure trois ans.'

test('the passage is highlighted where it is, the rest of the page is kept', () => {
  const match = highlightPassage(PAGE, 'Le bail dure trois ans.')

  assert.deepEqual(match.segments.map((segment) => segment.text).join(''), PAGE)
  assert.deepEqual(marked(PAGE, 'Le bail dure trois ans.'), ['Le bail dure trois ans.'])
  assert.ok(match.matched && match.firstFound && match.lastFound)
})

test('line breaks, extra spaces and case do not matter', () => {
  assert.deepEqual(marked(PAGE, 'le  LOCATAIRE paie son loyer chaque mois.'), [
    'Le locataire paie son loyer\nchaque mois.',
  ])
})

test('an excerpt truncated with ellipses is found by its fragments', () => {
  assert.deepEqual(marked(PAGE, '... Le locataire paie son loyer ... Le bail dure trois ans ...'), [
    'Le locataire paie son loyer',
    'Le bail dure trois ans',
  ])
})

test('a passage of several paragraphs highlights each of them', () => {
  assert.deepEqual(marked(PAGE, 'Article 1\nLe locataire paie son loyer\nchaque mois.\n\nArticle 2'), [
    'Article 1\nLe locataire paie son loyer\nchaque mois.',
    'Article 2',
  ])
})

test('an excerpt that summarizes the zone is found by its first words', () => {
  const page = 'Le bail dure trois ans à compter de la signature du contrat et se renouvelle.'

  assert.deepEqual(marked(page, 'Le bail dure trois ans à compter de la signature, puis renouvellement tacite.'), [
    'Le bail dure trois ans à compter de',
  ])
})

test('nothing is highlighted when the passage is not on the page', () => {
  const match = highlightPassage(PAGE, "Le propriétaire entretient l'immeuble")

  assert.equal(match.matched, false)
  assert.deepEqual(match.segments, [{ text: PAGE, highlighted: false }])
})

test('an empty passage or an empty page highlights nothing', () => {
  assert.equal(highlightPassage(PAGE, '').matched, false)
  assert.equal(highlightPassage(PAGE, '...').matched, false)
  assert.equal(highlightPassage(PAGE, null).matched, false)
  assert.deepEqual(highlightPassage('', 'texte').segments, [])
})

test('a passage that goes on over the page break has its last fragment missing from the first page', () => {
  const passage = 'Le bail dure trois ans.\n\nIl est renouvelable.'

  const first = highlightPassage(PAGE, passage)
  const second = highlightPassage('Il est renouvelable.\nArticle 3', passage)

  assert.ok(first.matched && first.firstFound && !first.lastFound)
  assert.ok(second.matched && !second.firstFound && second.lastFound)
})

test('regular expression characters in the passage are taken literally', () => {
  assert.deepEqual(marked('Prix (HT) : 5,00 € [net]', 'Prix (HT) : 5,00 € [net]'), ['Prix (HT) : 5,00 € [net]'])
})

test('a fragment is looked for after the previous one, so a repeated word does not take the first place', () => {
  const page = 'Total 10\nAutre ligne\nTotal 20'

  assert.deepEqual(marked(page, 'Autre ligne\n\nTotal 20'), ['Autre ligne', 'Total 20'])
})

test('an interval of characters is highlighted exactly, even when the same words are there twice', () => {
  const page = 'Total : 10 euros. Autre chose. Total : 10 euros.'
  const second = page.lastIndexOf('Total')

  const match = highlightRange(page, second, second + 17)

  assert.deepEqual(match.segments, [
    { text: 'Total : 10 euros. Autre chose. ', highlighted: false },
    { text: 'Total : 10 euros.', highlighted: true },
  ])
  assert.ok(match.matched)
})

test('an interval beyond the page is brought back to it, and an empty or reversed one highlights nothing', () => {
  assert.deepEqual(highlightRange('Un texte', 3, 99).segments, [
    { text: 'Un ', highlighted: false },
    { text: 'texte', highlighted: true },
  ])
  assert.equal(highlightRange('Un texte', 5, 5).matched, false)
  assert.equal(highlightRange('Un texte', 6, 2).matched, false)
  assert.equal(highlightRange('Un texte', 40, 50).matched, false)
  assert.deepEqual(highlightRange('', 0, 4).segments, [])
})

test('several intervals are highlighted, in the page order whatever the order they come in', () => {
  const page = 'Alpha un. Beta deux. Gamma trois.'

  const match = highlightRanges(page, [
    { start: 21, end: 33 },
    { start: 0, end: 9 },
  ])

  assert.deepEqual(
    match.segments.filter((segment) => segment.highlighted).map((segment) => segment.text),
    ['Alpha un.', 'Gamma trois.'],
  )
  assert.equal(match.segments.map((segment) => segment.text).join(''), page)
})

test('an interval inside another is not highlighted twice', () => {
  const match = highlightRanges('abcdefghij', [
    { start: 0, end: 8 },
    { start: 2, end: 5 },
  ])

  assert.deepEqual(match.segments, [
    { text: 'abcdefgh', highlighted: true },
    { text: 'ij', highlighted: false },
  ])
})

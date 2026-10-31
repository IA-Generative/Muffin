import assert from 'node:assert/strict'
import { test } from 'node:test'
import { documentFileUrl, hasFile, opensAtPage, pageWithin } from './documentFile.ts'

const BASE = 'https://muffin.test'

test('the file is downloaded from its own route, and opened in the browser only when asked', () => {
  assert.equal(documentFileUrl(BASE, 'c1', 'd1'), 'https://muffin.test/api/collections/c1/documents/d1/file')
  assert.equal(
    documentFileUrl(BASE, 'c1', 'd1', { inline: true }),
    'https://muffin.test/api/collections/c1/documents/d1/file?inline=true',
  )
})

test('a PDF opens on a page with the fragment the browser reads', () => {
  assert.equal(
    documentFileUrl(BASE, 'c1', 'd1', { inline: true, page: 7 }),
    'https://muffin.test/api/collections/c1/documents/d1/file?inline=true#page=7',
  )
  assert.equal(documentFileUrl(BASE, 'c1', 'd1', { page: 0 }), 'https://muffin.test/api/collections/c1/documents/d1/file')
})

test('a web page has no file to download', () => {
  assert.equal(hasFile('https://example.com/article'), false)
  assert.equal(hasFile('HTTP://example.com'), false)
  assert.equal(hasFile('rapport.pdf'), true)
  assert.equal(hasFile('http-guide.pdf'), true)
})

test('only a PDF opens at a page', () => {
  assert.equal(opensAtPage('Rapport 2025.PDF'), true)
  assert.equal(opensAtPage('notes.docx'), false)
  assert.equal(opensAtPage('pdf'), false)
})

test('a page typed by the reader stays inside the document', () => {
  assert.equal(pageWithin('12', 40), 12)
  assert.equal(pageWithin(' 3 ', 40), 3)
  assert.equal(pageWithin('0', 40), undefined)
  assert.equal(pageWithin('41', 40), undefined)
  assert.equal(pageWithin('abc', 40), undefined)
  assert.equal(pageWithin('', 40), undefined)
  assert.equal(pageWithin(5, 5), 5)
})

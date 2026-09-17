import { chromium } from '@playwright/test'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Se connecter' }).click()
await page.waitForURL(/realms\/muffin\/protocol\/openid-connect\/auth/)
await page.getByLabel('Username or email').fill('michou')
await page.getByLabel('Password', { exact: true }).fill('muffin-dev')
await page.getByRole('button', { name: 'Sign In' }).click()
await page.waitForURL(/localhost:5173\//)
await page.waitForTimeout(500)

// Create a collection with a real document so the agent has something to
// actually find via full-text search.
const collection = await page.evaluate(async () => {
  const r = await fetch('http://localhost:8000/api/collections', { method: 'POST', credentials: 'include' })
  return r.json()
})
console.log('Created collection', collection.id)

await page.evaluate(async (collectionId) => {
  await fetch(`http://localhost:8000/api/collections/${collectionId}/documents/url`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: 'https://example.com' }),
  })
}, collection.id)

// Wait for the document pipeline to index it (chunking is what gates it).
for (let i = 0; i < 20; i++) {
  await page.waitForTimeout(1000)
  const docs = await page.evaluate(async (collectionId) => {
    const r = await fetch(`http://localhost:8000/api/collections/${collectionId}/documents`, {
      credentials: 'include',
    })
    return r.json()
  }, collection.id)
  if (docs[0]?.status === 'indexed') {
    console.log('Document indexed')
    break
  }
}

// Now create a real research run.
const run = await page.evaluate(async () => {
  const r = await fetch('http://localhost:8000/api/runs', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'What is Example Domain used for?' }),
  })
  return r.json()
})
console.log('Created run', run.id, run.status)

let finalRun = run
for (let i = 0; i < 30; i++) {
  await page.waitForTimeout(1500)
  finalRun = await page.evaluate(async (runId) => {
    const r = await fetch(`http://localhost:8000/api/runs/${runId}`, { credentials: 'include' })
    return r.json()
  }, run.id)
  console.log(`poll ${i}: status=${finalRun.status} node=${finalRun.current_node}`)
  if (['completed', 'failed', 'cancelled'].includes(finalRun.status)) break
}

console.log('Final run:', JSON.stringify(finalRun, null, 2))

const events = await page.evaluate(async (runId) => {
  const r = await fetch(`http://localhost:8000/api/runs/${runId}/events?page_size=100`, { credentials: 'include' })
  return r.json()
}, run.id)
console.log(
  'Events:',
  events.items.map((e) => e.type),
)

await page.evaluate(async (collectionId) => {
}, collection.id)

await browser.close()

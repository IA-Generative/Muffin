// Takes a screenshot of the running dev server and saves it under docs/images.
// Usage: node scripts/screenshot.mjs <output-name> [path] [url]
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const [name, path = '/', baseUrl = 'http://localhost:5173'] = process.argv.slice(2)
if (!name) {
  console.error('Usage: node scripts/screenshot.mjs <output-name> [path] [url]')
  process.exit(1)
}

const root = dirname(fileURLToPath(import.meta.url))
const outDir = resolve(root, '../../docs/images')
mkdirSync(outDir, { recursive: true })
const outPath = resolve(outDir, `${name}.png`)

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
await page.goto(new URL(path, baseUrl).toString(), { waitUntil: 'networkidle' })
await page.screenshot({ path: outPath, fullPage: true })
await browser.close()

console.log(`Saved ${outPath}`)

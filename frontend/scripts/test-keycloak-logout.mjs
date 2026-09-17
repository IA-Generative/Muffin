import { chromium } from '@playwright/test'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

await page.goto('http://localhost:8081/', { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Se connecter' }).click()
await page.waitForURL(/realms\/muffin\/protocol\/openid-connect\/auth/)
await page.getByLabel('Username or email').fill('michou')
await page.getByLabel('Password', { exact: true }).fill('muffin-dev')
await page.getByRole('button', { name: 'Sign In' }).click()
await page.waitForURL('http://localhost:8081/')

await page.getByRole('button', { name: /Michou Dev/ }).click()
await page.getByRole('menuitem', { name: 'Se déconnecter' }).click()
await page.waitForTimeout(1000)
await page.screenshot({ path: '/tmp/4-after-logout.png' })
console.log('URL after logout:', page.url())

await browser.close()

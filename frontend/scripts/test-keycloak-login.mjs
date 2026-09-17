import { chromium } from '@playwright/test'

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })

await page.goto('http://localhost:8081/', { waitUntil: 'networkidle' })
await page.screenshot({ path: '/tmp/1-before-login.png' })

await page.getByRole('button', { name: 'Se connecter' }).click()
await page.waitForURL(/realms\/muffin\/protocol\/openid-connect\/auth/)
await page.screenshot({ path: '/tmp/2-keycloak-login-page.png' })

await page.getByLabel('Username or email').fill('michou')
await page.getByLabel('Password', { exact: true }).fill('muffin-dev')
await page.getByRole('button', { name: 'Sign In' }).click()

await page.waitForURL('http://localhost:8081/')
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/3-after-login.png' })

const name = await page.locator('.chat-sidebar__user-name').textContent()
const email = await page.locator('.chat-sidebar__user-email').textContent()
console.log('Logged in as:', name, email)

await browser.close()

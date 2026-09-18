import assert from 'node:assert/strict'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { loadConfigFromFile } from 'vite'


const mobileRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
)
const inventoryRoot = path.resolve(mobileRoot, '..')

async function loadProxy(configPath, backendTarget) {
  const previous = process.env.E2E_BACKEND_TARGET
  if (backendTarget === undefined) delete process.env.E2E_BACKEND_TARGET
  else process.env.E2E_BACKEND_TARGET = backendTarget
  try {
    const loaded = await loadConfigFromFile(
      { command: 'serve', mode: 'test' },
      configPath,
    )
    assert.ok(loaded)
    return loaded.config.server?.proxy
  } finally {
    if (previous === undefined) delete process.env.E2E_BACKEND_TARGET
    else process.env.E2E_BACKEND_TARGET = previous
  }
}

for (const [name, configPath] of [
  ['desktop', path.join(inventoryRoot, 'frontend', 'vite.config.ts')],
  ['mobile', path.join(mobileRoot, 'vite.config.ts')],
]) {
  test(`${name} dev server proxies authenticated backend routes`, async () => {
    const proxy = await loadProxy(configPath)

    assert.deepEqual(Object.keys(proxy ?? {}).sort(), ['/api', '/auth', '/web'])
    assert.equal(proxy?.['/auth'].target, 'http://localhost:5001')
  })

  test(`${name} dev server applies the E2E backend target`, async () => {
    const proxy = await loadProxy(configPath, 'http://e2e-app:5001')

    for (const pathPrefix of ['/api', '/auth', '/web']) {
      assert.equal(proxy?.[pathPrefix].target, 'http://e2e-app:5001')
    }
  })
}

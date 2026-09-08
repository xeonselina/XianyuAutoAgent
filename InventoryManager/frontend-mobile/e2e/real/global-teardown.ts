import { rm } from 'node:fs/promises'

import { realAuthStatePath } from '../helpers/real-backend'


export default async function globalTeardown() {
  await rm(realAuthStatePath, { force: true })
}

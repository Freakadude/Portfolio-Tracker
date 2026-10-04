// Run before the e2e server starts so the wizard test always sees a fresh install.
import { rmSync } from 'node:fs'

rmSync('e2e-data', { recursive: true, force: true })

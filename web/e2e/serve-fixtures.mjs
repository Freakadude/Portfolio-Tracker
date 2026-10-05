// Serves the recorded news feeds on a local port, so the end-to-end tests can preview a feed
// without contacting any real site.
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const dir = resolve('web/../tests/fixtures/news')
const types = { '.xml': 'application/rss+xml' }

createServer((request, response) => {
  const name = (request.url ?? '').replace(/^\//, '').split('?')[0]
  if (!/^[a-z_]+\.xml$/.test(name)) {
    response.writeHead(404).end()
    return
  }
  try {
    const body = readFileSync(resolve(dir, name))
    response.writeHead(200, { 'content-type': types['.xml'] }).end(body)
  } catch {
    response.writeHead(404).end()
  }
}).listen(8766, '127.0.0.1')

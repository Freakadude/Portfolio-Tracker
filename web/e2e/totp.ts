import { createHmac } from 'node:crypto'

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

function base32(secret: string): Buffer {
  const bits = secret
    .replace(/[\s=]/g, '')
    .toUpperCase()
    .split('')
    .map((c) => ALPHABET.indexOf(c).toString(2).padStart(5, '0'))
    .join('')
  const bytes = bits.match(/.{8}/g) ?? []
  return Buffer.from(bytes.map((b) => parseInt(b, 2)))
}

/** The six-digit code an authenticator app shows (RFC 6238) for the secret, `offsetSteps` of 30
 * seconds from now. */
export function codeFor(secret: string, offsetSteps = 0): string {
  const counter = Math.floor(Date.now() / 1000 / 30) + offsetSteps
  const message = Buffer.alloc(8)
  message.writeBigUInt64BE(BigInt(counter))
  const digest = createHmac('sha1', base32(secret)).update(message).digest()
  const offset = digest[digest.length - 1] & 0x0f
  const value = digest.readUInt32BE(offset) & 0x7fffffff
  return String(value % 1_000_000).padStart(6, '0')
}

# ADR 0042: An optional second factor with TOTP, recovery codes and segno

Status: accepted (2026-10-06). Covers FR-SY-03.

## Context
The login is a password with a throttle. FR-SY-03 asks for an optional TOTP second factor with recovery codes. Folio is reached over the LAN or Tailscale only, so this is defence in depth for one owner. The `app_user` table already had a `totp_secret_enc` column.

## Decision
- TOTP is RFC 6238 on the standard library (HMAC-SHA1, 30 s steps, six digits: what authenticator apps expect), checked against the RFC test vectors. A code is accepted for its own step and one either side, always comparing every step in constant time, and never twice: the step of the last accepted code is stored (`totp_last_step`) and a code from that step or earlier is refused, so a code seen over a shoulder or in a log is worth nothing a second time. Non-ASCII digits are refused before comparison (found by a test: they raised an error).
- The shared secret is stored encrypted with a key derived from `FOLIO_SECRET_KEY` for its own purpose, apart from the stored API keys. Setting up stores it unconfirmed and changes nothing at sign-in; only a valid code (`enable`) turns the factor on. The login then answers `401 Code needed` (`code: totp_required`) after a correct password and a wrong or missing code never gets a session. A missing code is not counted as a failure (the next request supplies it); a wrong code is, through the same throttle as passwords, and the throttle's counters are cleared only after the whole sign-in succeeds.
- Ten recovery codes (12 unambiguous characters, 60 bits, shown as `XXXX-XXXX-XXXX`) are made when the factor is turned on or renewed; only argon2id hashes are kept (`recovery_code`), each works once and keeps the time it was used. They are checked only when the value is the shape of one, so a mistyped six-digit code costs no hashing.
- Turning the factor off and replacing the recovery codes both need the password and a valid code (or recovery code), so a stolen session alone cannot remove it. Every change is audited, with no secret or code in the record.
- The QR code is drawn on the server by `segno` (one new dependency, pure Python, no dependencies of its own) as an SVG without a fixed size, and shown as an image from a data URL (never injected as markup). The key is shown as text too, for apps that take it by hand.

## Consequences
Losing both the phone and the recovery codes locks the owner out of the web app; the recovery is on the host (clear `totp_enabled` in the database, or restore a backup), which is the same trust boundary as the data. Existing sessions stay valid when the factor is turned on.

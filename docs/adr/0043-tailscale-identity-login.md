# ADR 0043: Tailscale Serve identity as an optional sign-in, trusted only from a named address

Status: accepted (2026-10-06). Covers FR-SY-04.

## Context
Tailscale Serve can pass the tailnet login of the connecting person in `Tailscale-User-Login`. FR-SY-04 (Could) asks to trust it as a login, restricted to a configured tailnet user and disabled by default. The risk is the header itself: any client that can reach Folio directly can write it.

## Decision
- Off unless both `FOLIO_TAILSCALE_USER` (the login that may sign in) and `FOLIO_TRUSTED_PROXIES` (the addresses or ranges Tailscale Serve connects from, as Folio sees them) are set. The check is: the TCP peer is inside the trusted list, then the header equals the configured user (case-insensitive). The peer check comes first; a peer that is not an IP address (a test client, a unix socket) is never trusted. Names and the list live in the environment, not in the database or the settings page, so a stolen session cannot widen them.
- `uvicorn` no longer rewrites the client address from forwarded headers (`proxy_headers=False`): otherwise a request from a loopback peer could claim any address with `X-Forwarded-For`, defeating the peer check. `X-Forwarded-Proto` is read by the app itself, so the secure-cookie behaviour is unchanged, and in the Docker setup (the peer is the bridge gateway, not loopback) nothing used the forwarded address before.
- `GET /auth/methods` says whether this request qualifies (no session is granted), so the login page can show a button; `POST /auth/tailscale` then starts a normal session for the owner (the one user), with the tailnet login written to the audit log. It is a POST so it carries the CSRF check like every other state change. Anything else gets a plain `401 Not available`, saying nothing about which part failed.
- A tailnet sign-in does not ask for the TOTP code: the device was already identified by the tailnet's keys, which is a stronger factor than a code typed into a page. Password sign-in still asks for the code when it is on.
- A malformed address list stops `folio web` at start with a message that names the bad entry, rather than failing closed silently later.

## Consequences
The owner has to find the address Tailscale Serve connects from (the Docker network gateway when it runs on the host); `docs/deployment.md` says how, and warns not to list an address other devices can use. If that address is shared with an untrusted client, the header cannot be trusted and this feature must stay off.

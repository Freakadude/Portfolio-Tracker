# ADR 0033: CI publishes the image to GHCR; compose pulls it

Status: accepted (2026-10-05). Refines ADR 0003.

## Context
ADR 0003 left the image unpublished: Portainer would have had to build it on the LXC from a checkout and read a `.env` file that a Portainer stack does not have. The owner asked for a painless deployment before Phase 5.

## Decision
- CI gets a `publish` job that runs only for a push to `main`, after the python, web, image and secrets jobs pass. It builds the multi-arch image (amd64, arm64) and pushes `ghcr.io/freakadude/portfolio-tracker:latest` and `:sha-<commit>`, logging in with the workflow's own `GITHUB_TOKEN` (`packages: write` for that job only). No token is stored anywhere.
- `docker-compose.yml` pulls that image (`FOLIO_IMAGE` can pin another tag) and takes its settings from the stack's environment variables instead of `env_file`, so it works from Portainer's editor or repository stack. `FOLIO_SECRET_KEY` and `FOLIO_LAN_IP` are required; the others are passed on only when set. The `build:` section moved to `docker-compose.build.yml`, an optional override.
- The package is public (owner decision, 2026-10-06; the repository is public as well). A private package with a `read:packages`, then `write:packages`, token in Portainer's registries still failed: the stack's pull reached GHCR without the login and got "unauthorized". The image holds the code but no secrets or data, which stay in the volume on the LXC.

## Consequences
An update is "Update the stack, re-pull image". A broken main never publishes. The rollback is an older `sha-` tag, with a backup first because migrations only go forward. The first publish cannot be verified before it runs on GitHub, so the first green push to main is its test.

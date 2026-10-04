# ADR 0003: Container image is built and verified in CI

Status: accepted (2026-10-04)

## Context
Each phase ends with a built image and a locally run compose stack. Docker is not installed on the development machine.

## Decision
GitHub Actions builds the multi-arch image (amd64 and arm64, no push) as the phase-gate evidence. The real compose run happens when the owner deploys the stack through Portainer on the homelab LXC and checks `/healthz`.

## Consequences
Container problems surface in CI or at deployment rather than in a local compose run. If Docker is installed locally later, the local compose run becomes part of each phase end again.

# ADR 0002: Commit straight to main

Status: accepted (2026-10-04)

## Context
The spec's standing order defaults to one branch per phase with a pull request into `main` at each gate (Q13). The owner is the only developer and chose to commit straight to `main` instead.

## Decision
Claude Code commits and pushes directly to `main` after each finished feature or bug fix. All other rules of the standing order remain: tests and pre-commit hooks pass first, never `--no-verify`, never force-push or rewrite pushed history, stage files by path.

## Consequences
No PR review step; CI on `main` is the safety net. The owner may enable branch protection later; the standing order in CLAUDE.md would then need revisiting. The `.claude/settings.json` deny rules for force-push stay in place.

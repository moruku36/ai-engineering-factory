# Contributing Guide

## 1. Branch Strategy
- `main`: Protected integration branch. Enforced by GitHub Ruleset (Pull Request required, CI checks required, non-fast-forward push blocked). Direct pushes and force pushes are strictly prohibited.
- `phase/p<N>-<name>`: Integration branch for Phase N development.
- `task/<id>`: Isolated branch for individual tasks (e.g., `task/smp-001`).


## 2. Commit Guidelines
- Use conventional commit format prefixed with Task ID: `feat(FND-002): add schema validation engine`.
- Do NOT squash or create giant commits. Maintain atomic, reviewable commits.
- History rewriting (`push --force`, rebase of shared branches) is forbidden.

## 3. Pull Request & Merging
- All code changes must target the designated phase branch or main branch via Pull Request.
- Required CI checks (lint, type/schema verification, unit tests, secret scanning) must pass.
- Human review and approval are mandatory. Automated merges are prohibited.

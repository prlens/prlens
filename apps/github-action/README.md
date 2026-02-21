# prlens GitHub Action

Run `prlens init` to automatically generate `.github/workflows/prlens.yml`
with the correct permissions, secrets, and trigger configuration.

The generated workflow:
- Triggers on `pull_request` events (opened, synchronize, reopened)
- Installs prlens and the chosen AI provider
- Runs `prlens review --yes` using the built-in `GITHUB_TOKEN` (no PAT needed)
- Posts inline review comments directly on the PR

## Manual Setup

If you prefer to set up the workflow manually, copy the template from
`prlens init` output or refer to the prlens documentation.

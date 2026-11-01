# CI

How `.github/workflows/ci.yml` gates main and pull requests.

## The gate

The job runs on a GitHub-hosted `ubuntu-24.04` runner with no container.
agentic-os's `actions/setup-ci` installs just, uv and pre-commit, and
`just check` runs unchanged, so a local `just check` tests the same thing. A
second step runs `just pre-commit`, with `~/.cache/pre-commit` cached on
`.pre-commit-config.yaml`, because the hook pin now names GitHub.

## The cache

uv resolves through PyPI on a cold cache. The job caches `~/.cache/uv` keyed on
`uv.lock` and raises uv's HTTP timeout to 180s.

## Beside publishing

A tag can point at any commit and ci.yml gates only main and pull requests, so
the publish train runs `just check` again. The tag reaches `just release-check`
through `RELEASE_TAG` rather than the run line, so shell metacharacters stay
data. The rest of the release train is [`publishing.md`](publishing.md).

## The retired Forgejo gate

`.forgejo/workflows/ci.yml` ran the same gate on a `docker` runner inside the
moving `:release` aos dev-base image. Forgejo was deleted on 2026-11-01 and the
file went in COI-3104. This repo is public, so no job here targets the
self-hosted `kai-server` runner.

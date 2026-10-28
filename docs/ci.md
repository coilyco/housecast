# CI

How `.forgejo/workflows/ci.yml` gates main and pull requests.

## The image

Every step runs a justfile recipe in the moving `:release` aos dev-base image,
which already ships uv, Python 3.12 and 3.13, just, pre-commit and trufflehog, so
the job needs no setup actions and a local `just` run checks the same thing.

## The caches

uv resolves through PyPI on a cold cache, and that egress flakes on this runner.
The job caches `~/.cache/uv` and the pre-commit cache and raises uv's 30s HTTP
timeout, because hook environments dominate a cold `just pre-commit`.

## The runner

The gate needs an Actions runner labelled `docker` attached to the repository.
Without one the workflow is still correct and starts gating once one is attached.

## Beside publishing

A tag can point at any commit and ci.yml gates only main and pull requests, so
publish.yml runs `just check` again. The tag reaches `just release-check` through
`RELEASE_TAG` rather than the run line, so shell metacharacters stay data. The
rest of the release train is [`publishing.md`](publishing.md).

## The hosted twin

`.github/workflows/ci.yml` runs the same gate on a GitHub-hosted `ubuntu-24.04`
runner with no container. agentic-os's `actions/setup-ci` installs just, uv and
pre-commit, and `just check` runs unchanged. It skips `just pre-commit` until the
hook pin moves off Forgejo, so it is the offline gate only. The Forgejo workflow
keeps running until this repo flips.

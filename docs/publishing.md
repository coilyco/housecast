# Publishing to PyPI

How a `housecast-v*` tag becomes a release.

## The train

`.github/workflows/publish.yml` fires on a pushed `housecast-v*` tag. It checks
the tag against the packaged version, runs `just check`, builds, then uploads.
PyPI accepts a filename once, so both gates run before the build. The job runs
on a GitHub-hosted runner (COI-3104).

## The rehearsal

`workflow_dispatch` takes an `index` input defaulting to `testpypi`, so a
hand-run is harmless and a real upload is deliberate. A `testpypi` run skips the
tag guard and builds whatever the ref holds, proving build, auth, and upload
from a branch without spending a version. `pypi` retries a release by tag.

## The tag guard

`scripts/release_tag.py` refuses a tag naming a version other than the one in
`housecast/__init__.py`. That failure already happened in its softer form here:
`housecast-v0.1.3` reports 0.1.1, and a git dependency does not check metadata.
Tested in `housecast/tests/test_release_tag.py`.

## The tokens

The train was written when the forge was Forgejo, which is not a trusted
publishing identity provider, so it uses API tokens. Moving trusted publishing
to GitHub is a separate change. `PYPI_TOKEN` and
`TEST_PYPI_TOKEN` are repository Actions secrets written from SSM by agentic-os
`just sync-actions-secrets`, each reaching uv through
`UV_PUBLISH_TOKEN` rather than argv. Both recipes pass `--check-url`, so a rerun
after a partial upload skips files already on that index.

## What ships

The wheel carries both packages, the grading page's assets, three `py.typed`
markers, and both licence files. The sdist carries the allowlist in
`pyproject.toml`: the package, docs, README and licences.

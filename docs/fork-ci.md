# Public builds and upstream release upgrade PRs

Maintain our source changes on `main`. There are no checked-in patch files to maintain.
Upstream workflow files and Dockerfiles remain unchanged.

```text
Official stable release
    -> create an upgrade branch from the fork's main changes, rebased onto that release
    -> open a PR into main
    -> run frontend, backend, recipe and image checks on the PR
    -> review and merge the PR
    -> main CI checks and publishes the versioned Docker image
```

The release detector never publishes images or merges its PR. These workflows do not
deploy to Kubernetes or change Flux, Helm or the live PostgreSQL database.

| Workflow | Purpose |
| --- | --- |
| `fork-ci.yml` | PR/main frontend checks, public backend API regressions, source/rebase tests and image build. PRs upload an amd64 image artifact; main publishes to GHCR. |
| `fork-image.yml` | Shared public CE feature selection, unchanged upstream Dockerfile, image smoke checks and optional publication. |
| `fork-release.yml` | Every six hours, inspect the latest stable upstream release and open an upgrade PR. Manual dispatch accepts a stable release tag and runs only from main. |

## Main is the source of our changes

`.github/fork-upstream-base.json` records the upstream commit that the current main
tree is based on. It contains only an upstream SHA and optional release tag, not our
code or a saved patch. The initial base is `5f68eb9f4479bf209a34a34c857dd1d7e8de0eb9`,
an upstream main snapshot. The first upgrade may align that snapshot with an official
release of the same application version. The detector skips a release already included
in the recorded base.

The helper checks both the workflow's main ref and its exact checkout SHA against the
repository's current main. A stale run skips and lets the next run use the new main.
On a new release, the detector snapshots main and derives its complete diff against
that base. In an isolated worktree it replays that diff as one temporary commit and
runs `git rebase --onto <release> <base>`. This carries our production changes, added
workflows, documentation and tests from main onto the new official source.

After rebase, the upgrade branch updates the upstream-base record. Its final commit
preserves main and release ancestry so the PR shows the version-update diff against
main. Main itself is never force-pushed or rewritten. The base record also makes a
subsequent upgrade work after squash-merging the PR.

A rebase conflict stops before pushing a branch or creating a PR. Fix the conflicting
main change or handle the upgrade manually, then rerun. There is no forced application,
automatic conflict resolution or fallback to an unmodified upstream build.

One open PR per release is reused. Its branch is named
`automation/windmill-v<version>-<main-sha>`. Closed PRs for the same main snapshot are
not reopened. An existing pushed branch can be reused if PR creation previously failed.
The scheduled check selects the latest stable release, not every historical or
intermediate release; dispatch a particular stable tag when needed.

## PR tests before publication

Bot-created PRs use `GITHUB_TOKEN`. GitHub does not automatically trigger ordinary
`pull_request` workflows for those PRs, so the detector explicitly dispatches
`fork-ci.yml` on the upgrade branch. Its checks appear on the PR's head commit.
If dispatch fails, the next detector run retries it when the PR has no CI run.

PR/main checks run the frontend regression suites and public backend API regressions.
Python tests exercise real Git diff/application/rebase, preservation of both main's
changes and new upstream code, patch conflicts, subsequent upgrades after a squash
merge, feature filtering and release-tag validation.

Every image starts against a disposable PostgreSQL 16 database. Smoke checks verify
the embedded frontend, password login, rejection of unauthenticated workspace creation,
creating four workspaces, archiving two and restoring one above the old cap.

PR builds upload an image archive and do not push to a registry. Only successful main
checks can publish. There is no auto-merge. Configure branch protection to require
these checks if merging a failing PR must be prohibited by GitHub itself.

## Official recipe and public features

The official `.github/workflows/docker-image.yml` checks out public source plus
`windmill-ee-private`, substitutes private implementations, then builds the root
Dockerfile with `features=ce`. It uses Ubicloud and Depot and also publishes variants.
It does not expose `workflow_call`. Its CE recipe requires private source too.

Our shared builder uses the root Dockerfile in the source being tested. After an
upgrade PR, that is the new release's Dockerfile. GitHub-hosted runners and Docker
Buildx replace Ubicloud and Depot. `fork_build.py` derives the public CE feature graph,
excluding `private`, `no_auth` and enterprise groups. Current selection:

```text
oss_core,operator,all_languages,jemalloc,dind,agent_worker_server
```

Public feature selection does not supply private implementations. The public Operator
returns an unavailable error and agent-worker routes are stubs. Keep the existing
official Operator image. The `oss` preset is deliberately avoided because it enables
`no_auth`. Enabling language features does not install every runtime from the optional
`docker/DockerfileFull`; this workflow builds the default upstream image variant.

## Published images and provenance

Images use the lowercase fork repository, currently `ghcr.io/yeap-capital/windmill`:

- PR: `windmill-linux-amd64-<sha>` artifact, retained for seven days, no registry push.
- Main before the first release upgrade: `sha-<commit>`.
- Main after an upgrade: `1.856.0-yeap.<main-commit-prefix>`.

The shared builder supports native amd64/arm64 runners. PRs currently build amd64;
main publishes both architectures. A version manifest is published only after all
architecture builds and smoke checks pass. An interrupted publication may leave an
architecture tag without the final version manifest. No mutable latest tag is created.

Build metadata records the upstream base SHA/tag, fork SHA, selected features and
SHA256 of the production diff. That diff is generated during CI from main, excludes
fork build tooling and version-specific tests, and is saved only as a build artifact.
It is not an input maintained separately from main. Prefer the recorded manifest
digest when updating Flux. Publishing does not update the cluster automatically.

## Repository setup

Merge these workflows into the default main branch and enable Actions. Allow GitHub
Actions to create pull requests in repository settings. The detector requires contents
and pull-request write permissions, plus Actions write for explicit test dispatch.
GHCR publication uses `packages: write`; organization/package access policy can still
prevent it. Make the package public or configure Kubernetes pull credentials.

If an upstream upgrade modifies workflow files, GitHub may reject its branch push with
the default token. Configure `UPSTREAM_RELEASE_TOKEN` for git pushes, using a token
authorized for this repository with Contents and Workflows write access. Classic PATs
require the appropriate repo/public_repo and workflow scopes. PR creation and test
dispatch still use GITHUB_TOKEN, so tests are triggered once through explicit dispatch.

Keep source changes small and delete unwanted restrictions directly. Reuse upstream
build code. Original workflows retain their original infrastructure requirements;
disable them through the Actions UI if the fork should run only these public workflows.
The existing 1.804.0 deployment still requires a separate same-version backport before
an image-only replacement; the automated upgrade process targets newer releases.

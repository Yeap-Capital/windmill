# Release upgrade PRs and Docker publication

Maintain custom source changes in `main`. Existing upstream workflows and Dockerfiles
remain unchanged. No patch series, upstream-base record or Python PR automation is used.

## Upgrade an official release

`fork-release.yml` checks the latest stable upstream release every six hours. It also
accepts a release tag through manual dispatch from main. Git and GitHub CLI perform:

```text
fetch the official release tag
    -> create upstream/<tag> in this fork from that tag
    -> merge main into the release branch
    -> push the branch and open a PR back into main
    -> run frontend and backend tests on the PR
    -> review and merge the PR
    -> main CI builds and publishes Docker images
```

The workflow reuses an existing PR and skips a release already included in main. A
merge conflict stops before push/PR creation and needs normal manual resolution.
It never rewrites main or auto-merges a PR.

PRs created with `GITHUB_TOKEN` do not trigger ordinary PR workflows automatically.
The workflow explicitly dispatches `fork-ci.yml` when the upgrade branch has no CI run.
This runs tests on the PR head without building a Docker image.

## Tests and image builds

`fork-ci.yml` runs frontend checking/regressions and public backend API tests on PRs
and main pushes. Its Docker job requires a successful frontend/backend result and
**a push to main**. PR events and manual test dispatches do not build Docker images.

`fork-image.yml` is the shared publisher called only by that main job. It builds the
unchanged root Dockerfile for amd64 and arm64 on native GitHub runners, tests each
image against disposable PostgreSQL, then publishes to GHCR. Smoke checks cover
embedded frontend, password login, refusal of unauthenticated creation, and workspace
creation/archive/restore above the former caps.

Images use `ghcr.io/yeap-capital/windmill:<version>-yeap.<commit-prefix>`. The version
comes from Cargo.toml. The shared manifest is published after both architectures
pass; no mutable latest tag is created. Nothing deploys to Kubernetes or changes Flux.

The public CE build uses
`oss_core,operator,all_languages,jemalloc,dind,agent_worker_server`. It retains
authentication and excludes `private` and `no_auth`. Official CE also uses private
source, so this build cannot reproduce all of its features. Keep the existing official
Operator image: the public reconciler is unavailable. This builds the default image
variant, not the optional full runtime variant.

## Setup

Merge the workflows into main, enable Actions and allow Actions to create PRs.
The upgrade workflow needs contents/PR write and Actions write for test dispatch.
If an upstream merge changes workflow files, git pushes may require the optional
`UPSTREAM_RELEASE_TOKEN` with Contents and Workflows write access. PR creation and
test dispatch still use `GITHUB_TOKEN`. GHCR publication requires packages write.

Original upstream workflows retain their original infrastructure dependencies and
triggers. If enabled separately, disable the original Docker workflow in the Actions
UI to avoid its independent PR Docker builds; its source file need not be edited.

The existing 1.804.0 deployment still needs a same-version backport before an image-only
replacement. This workflow handles future release upgrades through reviewable PRs.

# Public builds and patched upstream releases

Upstream workflow files and Dockerfiles remain unchanged. The fork adds three entry
points with a shared image builder:

| Workflow | Purpose |
| --- | --- |
| `fork-ci.yml` | PR/main frontend checks, public backend API tests, patch/feature checks, then image build. PRs upload an amd64 image archive. Main builds publish a SHA tag. |
| `fork-image.yml` | Reusable source preparation, public CE feature selection, unchanged upstream Dockerfile, real image smoke checks and optional GHCR publication. |
| `fork-release.yml` | Every six hours, check the latest stable upstream release, apply our patches to that release and publish tested amd64/arm64 images. Manual dispatch accepts a stable release tag. |

Schedules and manual dispatch become available after these workflows reach the default
branch. Actions must be enabled in the fork. GHCR publication uses `GITHUB_TOKEN` with
`packages: write`; GitHub Release records use `contents: write`. Organization policy or
an existing package's access settings can still prevent publication. A newly created
GHCR package may be private; make it public or configure Kubernetes pull credentials.

These workflows publish images, not deployments. They do not change Flux, Helm, the
cluster, an upstream tracking branch or the live PostgreSQL database.

## Official recipe and public feature selection

The official `.github/workflows/docker-image.yml` checks out public source plus
`windmill-ee-private`, substitutes private implementations, then builds the root
Dockerfile with `features=ce`. It uses Ubicloud and Depot, publishes multiarchitecture
images and also has release/variant jobs. Its CE recipe requires private source too.
It does not expose `workflow_call`, so it cannot be directly called as a reusable workflow.

Our image builder uses the root Dockerfile from the source being built. On an upstream
release build this is that release's Dockerfile, not the Dockerfile from fork main.
GitHub-hosted runners and Docker Buildx replace Ubicloud and Depot.

`fork_build.py` reads that source's Cargo feature graph, expands `ce` only where needed,
and removes `private`, `no_auth` and enterprise feature groups. It refuses upstream
default features that enable these flags. For the current source this selects:

```text
oss_core,operator,all_languages,jemalloc,dind,agent_worker_server
```

This retains the public language feature group rather than the previous Python-only
build. It is not the `oss` preset, which enables `no_auth`. Compilation of a feature
does not supply absent private implementations: the public Operator returns an
unavailable error and agent-worker routes are stubs. Keep the existing official
Operator image. A public build is not functionally identical to the official CE image.

The upstream root image is the default variant. The optional full variant adds language
tools through `docker/DockerfileFull`; enabling Rust language features alone does not
install every tool from that full variant. This workflow does not build the full variant.

## Patch maintenance

`fork/patches/*.patch` is the ordered production patch series. The current patch deletes
the workspace-count functions, their call sites and frontend count guards. It adds no
quota switches or policy modules. Authentication and permission checks remain in place.

The patch was exported from the fork's upstream base
`5f68eb9f4479bf209a34a34c857dd1d7e8de0eb9`. Tests verify that applying it to that base
reproduces the fork's three changed production files, and that it applies to the
published upstream release `v1.855.1`. CI-only changes and Rust/TS test changes are not
part of the production patch.

To update the series, start a clean worktree at the intended upstream base, make only
our production changes, and export `git diff --binary` to the patch directory. Update
the patch tests' base and supported release when rebasing. Do not export the entire
fork diff including workflows, tests and unrelated upstream changes.

Each patch first passes `git apply --check`, then `git apply`. A conflict stops source
preparation and prevents image publication. There is no forced application, automatic
conflict resolution, skipped patch or fallback to unmodified upstream source. Repair
the patch and rerun the release workflow when upstream changes conflict with it.

The current patch conflicts with `v1.804.0`; that older deployment still needs a
separate backport before a same-version replacement. Do not use a 1.855.1 image as
an image-only replacement for that deployment.

## Checks and publication

PR/main checks retain the existing public backend integration tests and focused
frontend regression suites. New Python tests exercise actual patch application,
conflict handling, feature selection and release-tag validation.

Every architecture image is loaded locally and started against a disposable
PostgreSQL 16 database. Smoke checks verify:

- embedded frontend and password login;
- unauthenticated workspace creation is rejected;
- creating four workspaces, archiving two and restoring one above the former cap.

Release builds compile the patched upstream source and run these image checks; they
do not run the latest fork main's version-specific Rust/TS test suites against older
upstream source. Existing PR/main tests validate changes to the fork itself.

Only after an architecture passes does it push its architecture tag. The shared version
manifest is published only after every architecture passes. A failed build may leave
an architecture tag, but cannot create the completed version's manifest or Release record.

Image names use the lowercase fork repository, currently
`ghcr.io/yeap-capital/windmill`:

- PR: an artifact `windmill-linux-amd64-<sha>`, retained for seven days, no registry push.
- Main: `sha-<commit>`, currently amd64.
- Upstream release: `1.855.1-yeap.<build-revision>`, amd64 and arm64.

No mutable `latest` tag is published. Prefer the recorded manifest digest for Flux.
Native amd64/arm64 GitHub runners avoid emulating the Rust compiler.

After release image publication, a fork GitHub Release such as
`fork-v1.855.1-p<build-revision>` records the image digest, source SHA, fork SHA, selected
features and applied patch. The tag points to the fork workflow/recipe commit; the
metadata identifies the actual upstream source commit. It is not a commit of a merged
upstream source tree. The build revision hashes the patch series and image-building
scripts/workflow, so recipe or patch updates allow rebuilding the same upstream version.

The scheduled check selects GitHub's latest stable upstream release. It skips a completed
release with the same build revision, retries failed builds on subsequent checks, and
does not backfill every historical or intermediate release. Dispatch a specific tag
manually when needed. Publishing the completion record fails if GitHub Release write
access is denied, even if the image was already pushed; rerun after fixing access.

## Upstream merge policy

Prefer deleting unwanted restrictions over adding policy layers. Keep edits to upstream
source small. Reuse public upstream build code, and keep upstream workflow/Dockerfile
changes out of the fork diff. Original workflows retain their original triggers and
infrastructure dependencies. Disable them through the Actions UI if this fork should
run only these public workflows; this does not edit upstream YAML.

# Public fork CI

`.github/workflows/fork-ci.yml` is an independent entry point for this fork. Upstream
workflow files and the root Dockerfile are kept intact to simplify upstream merges.
The new workflow reuses upstream build commands and public toolchain actions on
GitHub-hosted Ubuntu runners, without private source, a license key, Ubicloud or Depot.

## Upstream merge policy

Prefer deleting unwanted restrictions over adding policy layers or switches. Reuse
upstream code and actions when they can meet the fork's needs. Keep necessary edits to
existing source small. Add a workflow only when the existing ones cannot run the required
checks, and leave upstream workflow files and Dockerfiles intact for future merges.

| Job | Checks |
| --- | --- |
| Frontend | Generate the API client, run `npm run check`, and run session-state and workspace-creation regression tests. |
| Backend | Migrate PostgreSQL 16, compile the public backend and run `workspace_count_limits` and `session_workspace_status` API tests with `quickjs`. |
| Docker | After both checks pass, build the upstream Dockerfile for Linux amd64, check the executable and upload an image archive. |

Draft PRs run too. Changes to the source paths or this workflow trigger it on PR updates
and main-branch pushes. Manual dispatch is available once the workflow is on the default
branch. It does not publish an image to a registry, release or deployment.

## Enable Actions

Open the repository's **Actions** tab and enable workflows if the fork has Actions
disabled. Check **Settings → Actions → General** if organization policy prevents runs.
After enabling Actions, push another commit to the PR branch, or use **Run workflow**
after this definition reaches the default branch.

The original upstream workflows still have their original triggers and infrastructure
requirements. Disable those workflows individually in GitHub's Actions UI if this fork
should run only **Public fork CI**. This changes repository settings without modifying
upstream YAML files.

Check each job's logs before treating an image as tested. These backend tests cover
workspace API regressions, not the private enterprise integration suite.

## Use the image

Download `windmill-linux-amd64-<sha>` from a successful **Public fork CI** run, unzip it,
then load and tag the archive:

```sh
docker load --input windmill-image.tar
docker tag windmill-fork:<sha> windmill-local:workspace-limits
```

The tag printed by `docker load` uses the workflow's `github.sha`; for a PR this is the
tested merge commit. Use `windmill-local:workspace-limits` in your deployment's image
configuration. The archive expires after seven days.

The image uses `features=oss_core,python`, avoiding `ce`'s private dependency and `oss`'s
`no_auth` flag. It includes the public core and Python, not every language or private
enterprise implementation. The executable check does not start or validate a deployment.

## Why a separate workflow

Upstream checks use Ubicloud runners. The backend integration suite also checks out
`windmill-ee-private` and enables `enterprise,private`; the workspace-count regression
test is community-only and is skipped with those features. The upstream Docker workflow
uses Depot and private source even for its CE build, and its PR trigger only matches
changes to the root Dockerfile. These dependencies and test targets differ from this
public fork, so reusing the workflow unchanged cannot replace this CI entry point.

Workspace count limits are removed directly from the backend and frontend. There are
no fork policy modules or new quota switches. Existing tests receive the required
expectation changes; the API lifecycle regression is a new test file.

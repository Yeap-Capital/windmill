# Public fork CI

The existing upstream workflow files also support public forks. They use GitHub-hosted
Ubuntu runners without `windmill-ee-private`, a license key, Ubicloud or Depot credentials.

| Workflow | PR checks |
| --- | --- |
| `frontend-check.yml` | Generate the API client, run `npm run check`, and run the session-state and workspace-creation regression tests. |
| `backend-test.yml` | Migrate a PostgreSQL 16 service, compile the public backend and run `workspace_count_limits` and `session_workspace_status` API integration tests with `quickjs`. |
| `docker-image.yml` | Build the root upstream `Dockerfile` for Linux amd64, check the image executable and upload a Docker image archive. |

Draft PRs run these checks too. Changes to their relevant source paths or workflow files
trigger the corresponding workflow. Each workflow also has a manual `workflow_dispatch`
entry once its definition is on the default branch. Main-branch source changes run the
checks and image build automatically.

The upstream backend checks and private integration suite are restricted to
`windmill-labs/windmill`; public forks use the public integration job instead. The Docker
release jobs still belong to upstream. Fork builds do not push to a container registry,
publish a release or deploy an instance.

## Enable Actions

New forks may have Actions disabled. Open the repository's **Actions** tab and enable
workflows. If runs still do not start, check **Settings → Actions → General** for the
repository or organization policy. After enabling Actions, push another commit to the
PR branch, or use **Run workflow** after the workflow is present on the default branch.

Check the run's jobs and logs before treating an image as tested. The public backend
job covers the workspace API regressions, not the private enterprise integration suite.

## Use the image

Download the `windmill-linux-amd64-<sha>` artifact from a successful Docker workflow run,
unzip it, then load and tag the archive:

```sh
docker load --input windmill-image.tar
docker tag windmill-fork:<sha> windmill-local:workspace-limits
```

The tag printed by `docker load` uses the workflow's `github.sha`; for a PR this is the
tested merge commit. Use `windmill-local:workspace-limits` in your deployment's image
configuration. The archive expires after seven days.

This image reuses the upstream Dockerfile with `features=oss_core,python`. This avoids
the `private` dependency of `ce` and the `no_auth` flag included by `oss`. It includes
the public core and Python, not every language or private enterprise implementation.
The image executable check does not start the API or verify a production deployment.

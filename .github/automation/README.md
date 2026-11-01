# Repository automation

Custom source changes live in main. Only the three repository workflows below are
retained; inherited upstream workflows, archived workflows and local Actions are removed.
Dockerfiles are unchanged. Scripts and these instructions are grouped in `.github/automation/`.
GitHub requires workflow entry files directly inside `.github/workflows/`; it does not
support workflow subdirectories.

| Entry | Behavior |
| --- | --- |
| `ci.yml` / CI | Automatically test frontend and public backend on PRs and main pushes. No image jobs or image workflow calls. |
| `upstream-pr.yml` / Upstream update PR | Every six hours, or manually on main, import the latest stable official release, merge main into its version branch and open a PR back into main. |
| `build-image.yml` / Build image | Only manual workflow_dispatch on main builds, validates and publishes amd64/arm64 images. Never called by CI or triggered by PRs/pushes. |

## Upstream update PRs

`upstream-pr.sh` uses Git and GitHub CLI. It fetches an official release tag, creates
`upstream/<tag>` in this repository, merges the main snapshot into it, pushes the branch
and opens a PR into main. Existing PRs and releases already included in main are skipped.
On every upgrade, it restores these three workflow entry files from main and removes
all other workflows and inherited local Actions, including newly added upstream files.
This resolves workflow-only merge conflicts according to that rule. Other merge conflicts
stop the job before push or PR creation. Main is never rewritten, and PRs are not auto-merged.

Configure the Actions secret `UPSTREAM_PR_TOKEN` with a PAT or externally managed App
token authorized for this repository. It needs Contents and Pull requests write access,
plus Workflows write access when upstream updates workflow files. Use this token for
both git pushes and PR creation so the normal pull_request event starts CI automatically.
The workflow does not dispatch CI and does not fall back to GITHUB_TOKEN. A regular
GITHUB_TOKEN may suppress downstream workflows or require approval for automated PRs.

## Manual image publication

After reviewing and merging an upgrade PR, select **Actions > Build image > Run workflow**
on main when an image is wanted. Nothing builds an image automatically on merge.

The workflow uses the unchanged upstream root Dockerfile with public CE features
`oss_core,operator,all_languages,jemalloc,dind,agent_worker_server`. It retains
authentication, excludes private/no_auth, and publishes native amd64/arm64 images to
`ghcr.io/yeap-capital/windmill:<version>-yeap.<commit-prefix>` after image smoke checks.
The shared manifest waits for both architectures to pass. No mutable latest tag or
Kubernetes/Flux deployment is performed. Publication requires packages write access.

Public source does not reproduce private CE implementations. Keep the existing
official Operator image; its public reconciler is unavailable. This builds the default
image variant, not the optional full runtime variant.

These workflows become available after merging into main and enabling Actions.
There are no retained upstream workflow entry files or automatic image-build workflows.

Sources: [workflow location](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#creating-a-reusable-workflow),
[tokens and automatic triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

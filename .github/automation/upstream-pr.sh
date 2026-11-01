#!/usr/bin/env bash
set -euo pipefail

# A PAT/App token makes PR creation trigger pull_request CI without dispatching CI.
: "${GH_TOKEN:?Configure UPSTREAM_PR_TOKEN with repository Contents, Pull requests and Workflows write access}"
: "${GITHUB_SHA:?Run this script through the upstream-pr workflow on main}"
gh auth setup-git

tag=${REQUESTED_TAG:-$(gh api repos/windmill-labs/windmill/releases/latest --jq .tag_name)}
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ $(gh api "repos/windmill-labs/windmill/releases/tags/$tag" --jq '.draft or .prerelease') == false ]]
branch="upstream/$tag"
existing_pr=$(gh pr list --head "$branch" --base main --state all --json url --jq '.[0].url // empty')
if [[ -n "$existing_pr" ]]; then
  echo "$existing_pr" >> "$GITHUB_STEP_SUMMARY"
  exit 0
fi

git fetch --no-tags https://github.com/windmill-labs/windmill.git "refs/tags/$tag:refs/tags/$tag"
if git merge-base --is-ancestor "refs/tags/$tag" "$GITHUB_SHA"; then exit 0; fi
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
if [[ -n $(git ls-remote --heads origin "refs/heads/$branch") ]]; then
  git fetch origin "refs/heads/$branch"
  git switch -c "$branch" FETCH_HEAD
else
  git switch -c "$branch" "refs/tags/$tag"
fi
git merge --no-edit "$GITHUB_SHA"
git push origin "$branch"

printf 'Import official Windmill %s and merge our main changes into that release.\n\nPR checks run frontend and backend tests automatically. Docker images are built only by manually running the Build image workflow on main.\n' "$tag" > "$RUNNER_TEMP/upgrade-pr.md"
gh pr create --base main --head "$branch" --title "chore: update Windmill to $tag" --body-file "$RUNNER_TEMP/upgrade-pr.md" >> "$GITHUB_STEP_SUMMARY"

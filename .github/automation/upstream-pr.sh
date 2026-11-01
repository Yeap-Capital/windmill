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
git merge --no-edit --no-ff --no-commit "$GITHUB_SHA" || [[ -f $(git rev-parse --git-path MERGE_HEAD) ]]
# Retain our entry files and discard upstream workflows/actions, including new ones.
git checkout "$GITHUB_SHA" -- .github/workflows/ci.yml .github/workflows/upstream-pr.yml .github/workflows/build-image.yml
while IFS= read -r -d '' path; do
  case "$path" in
    .github/workflows/ci.yml|.github/workflows/upstream-pr.yml|.github/workflows/build-image.yml) ;;
    *) git rm -f --ignore-unmatch -- "$path" ;;
  esac
done < <(git ls-files -z -- .github/workflows .github/actions)
if [[ -n $(git diff --name-only --diff-filter=U) ]]; then
  echo 'Unresolved merge conflicts remain outside workflow cleanup; resolve them before opening the PR.' >&2
  exit 1
fi
if [[ -f $(git rev-parse --git-path MERGE_HEAD) ]]; then
  git commit --no-edit
elif ! git diff --cached --quiet; then
  git commit -m 'Keep only repository automation'
fi
git push origin "$branch"

printf 'Import official Windmill %s and merge our main changes into that release.\n\nPR checks run frontend and backend tests automatically. Docker images are built only by manually running the Build image workflow on main.\n' "$tag" > "$RUNNER_TEMP/upgrade-pr.md"
gh pr create --base main --head "$branch" --title "chore: update Windmill to $tag" --body-file "$RUNNER_TEMP/upgrade-pr.md" >> "$GITHUB_STEP_SUMMARY"

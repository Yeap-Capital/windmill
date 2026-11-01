#!/usr/bin/env python3
"""Prepare public Windmill builds from the fork or a patched upstream release."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import urllib.request
import urllib.parse


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = "windmill-labs/windmill"
BASE_FILE = ".github/fork-upstream-base.json"
# Keep build orchestration and version-specific tests out of the runtime source patch.
PATCH_PATHS = [
    ".", ":(exclude).github", ":(exclude)docs/fork-ci.md", ":(exclude)fork",
    ":(exclude)backend/tests", ":(exclude,glob)**/*.test.*",
]


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def stable_tag(value):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", value):
        raise ValueError(f"Expected a stable upstream release tag, got {value!r}")
    return value


def upstream_base(root):
    base = json.loads((root / BASE_FILE).read_text())
    if not re.fullmatch(r"[a-f0-9]{40}", base["sha"]):
        raise ValueError("Invalid upstream base SHA")
    if base["tag"] is not None:
        stable_tag(base["tag"])
    return base


def fetch_base(root):
    base = upstream_base(root)["sha"]
    exists = subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"],
                            cwd=root, capture_output=True).returncode == 0
    if not exists:
        git("fetch", "--no-tags", f"https://github.com/{UPSTREAM}.git", base, cwd=root)


def generate_patch(root, base=None, production=True):
    base = base or upstream_base(root)["sha"]
    patch = subprocess.check_output(
        ["git", "diff", "--binary", "--no-renames", base, "HEAD", "--",
         *(PATCH_PATHS if production else ["."])], cwd=root,
    )
    return base, patch


def build_revision(root):
    return git("rev-parse", "HEAD", cwd=root)[:12]


def public_features(source):
    features = tomllib.loads((source / "backend/Cargo.toml").read_text())["features"]
    omitted = set()

    def forbidden(name):
        leaf = name.split("/")[-1]
        return leaf in {"private", "no_auth", "enterprise"} or leaf.startswith("enterprise_")

    def contains_forbidden(name, stack=()):
        if name in stack:
            raise ValueError(f"Cyclic Cargo feature: {name}")
        return forbidden(name) or any(
            contains_forbidden(child, (*stack, name)) for child in features.get(name, [])
        )

    def expand(name):
        if forbidden(name):
            omitted.add(name)
            return []
        if contains_forbidden(name):
            return [leaf for child in features[name] for leaf in expand(child)]
        return [name]

    if "ce" not in features or "oss_core" not in features:
        raise ValueError("Upstream CE feature layout changed; review the build recipe")
    if contains_forbidden("default"):
        raise ValueError("Upstream default features now enable a forbidden feature")
    selected = list(dict.fromkeys(expand("ce")))
    # Pass root feature names, never a dependency/private feature or the OSS no_auth preset.
    if not selected or any(name not in features for name in selected):
        raise ValueError(f"Unexpected public feature layout: {selected}")
    return ",".join(selected), sorted(omitted)


def apply_patch(source, patch):
    if patch:
        subprocess.run(["git", "apply", "--check"], input=patch, cwd=source, check=True)
        subprocess.run(["git", "apply"], input=patch, cwd=source, check=True)


def api(path, data=None):
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def outputs(values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("Multiline workflow output")
            output.write(f"{key}={value}\n")


def rebase_main(root, source, tag, target):
    """Replay the main tree delta once, preserving main and release ancestry in the PR."""
    base, patch = generate_patch(root, production=False)
    main_sha = git("rev-parse", "HEAD", cwd=root)
    git("worktree", "add", "--detach", str(source), base, cwd=root)
    git("config", "user.name", "github-actions[bot]", cwd=source)
    git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com", cwd=source)
    apply_patch(source, patch)
    git("add", "--all", cwd=source)
    git("commit", "--allow-empty", "-m", f"Apply fork main changes from {main_sha}", cwd=source)
    git("rebase", "--onto", target, base, cwd=source)
    (source / BASE_FILE).parent.mkdir(parents=True, exist_ok=True)
    (source / BASE_FILE).write_text(json.dumps({"sha": target, "tag": tag}, indent=2) + "\n")
    git("add", BASE_FILE, cwd=source)
    git("commit", "--amend", "--no-edit", cwd=source)
    tree = git("rev-parse", "HEAD^{tree}", cwd=source)
    # Keep the PR diff against main accurate and support future upgrades after squash merges.
    return git("commit-tree", tree, "-p", main_sha, "-p", target,
               "-m", f"Update Windmill to {tag}", cwd=source)


def upgrade(tag, source):
    if (os.environ.get("GITHUB_REF") != "refs/heads/main"
            or git("rev-parse", "HEAD", cwd=ROOT) != os.environ.get("GITHUB_SHA")):
        raise ValueError("Upgrade PRs must run from a checked-out main workflow snapshot")
    repository = os.environ["GITHUB_REPOSITORY"]
    remote_main = api(f"repos/{repository}/git/ref/heads/main")["object"]["sha"]
    if remote_main != os.environ["GITHUB_SHA"]:
        outputs({"created": "false", "reason": "Main advanced; the next run will use its new snapshot"})
        return
    endpoint = f"releases/tags/{stable_tag(tag)}" if tag else "releases/latest"
    release = api(f"repos/{UPSTREAM}/{endpoint}")
    if release["draft"] or release["prerelease"]:
        raise ValueError("Only published stable upstream releases are supported")
    tag = stable_tag(release["tag_name"])
    prefix = f"automation/windmill-{tag}-"
    branch = f"{prefix}{build_revision(ROOT)}"
    for pull in api(f"repos/{repository}/pulls?state=all&per_page=100"):
        if pull["head"]["repo"] is None or pull["head"]["repo"]["full_name"].lower() != repository.lower():
            continue
        if pull["state"] == "open" and pull["head"]["ref"].startswith(prefix):
            query = urllib.parse.urlencode({"branch": pull["head"]["ref"], "head_sha": pull["head"]["sha"], "per_page": 1})
            runs = api(f"repos/{repository}/actions/workflows/fork-ci.yml/runs?{query}")
            outputs({"created": "false", "pr_url": pull["html_url"],
                     "test_branch": "" if runs["workflow_runs"] else pull["head"]["ref"]})
            return
        if pull["state"] == "closed" and pull["head"]["ref"] == branch:
            outputs({"created": "false", "pr_url": pull["html_url"]})
            return
    fetch_base(ROOT)
    git("fetch", "--no-tags", f"https://github.com/{UPSTREAM}.git",
        f"refs/tags/{tag}:refs/tags/{tag}", cwd=ROOT)
    target = git("rev-parse", f"refs/tags/{tag}^{{commit}}", cwd=ROOT)
    if subprocess.run(["git", "merge-base", "--is-ancestor", target,
                       upstream_base(ROOT)["sha"]], cwd=ROOT).returncode == 0:
        outputs({"created": "false", "reason": "Release already included in main's upstream base"})
        return
    if not git("ls-remote", "--heads", "origin", f"refs/heads/{branch}", cwd=ROOT):
        commit = rebase_main(ROOT, source, tag, target)
        git("update-ref", f"refs/heads/{branch}", commit, cwd=ROOT)
        # A dedicated token can grant workflow-file writes needed by upstream upgrades.
        push_env = {**os.environ, "GH_TOKEN": os.environ.get("UPSTREAM_RELEASE_TOKEN") or os.environ["GH_TOKEN"]}
        subprocess.run(["git", "push", "origin", f"refs/heads/{branch}"],
                       cwd=ROOT, env=push_env, check=True)
    pull = api(f"repos/{repository}/pulls", {
        "title": f"chore: update Windmill to {tag}",
        "head": branch,
        "base": "main",
        "body": (
            f"Rebase the fork changes from main `{git('rev-parse', 'HEAD', cwd=ROOT)}` "
            f"onto official Windmill `{tag}` (`{target}`).\n\n"
            "Production changes, fork workflows and tests come from main. "
            "The upstream base record is updated in this PR. "
            "Public fork CI is dispatched explicitly so bot-created PRs run tests. "
            "PR builds do not publish images. After merge, main CI tests and publishes "
            "the versioned image. This PR does not deploy to Kubernetes."
        ),
    })
    outputs({"created": "true", "test_branch": branch, "pr_url": pull["html_url"]})


def prepare():
    fetch_base(ROOT)
    base, patch = generate_patch(ROOT)
    source = ROOT
    tag = upstream_base(ROOT)["tag"]
    features, omitted = public_features(source)
    revision = build_revision(ROOT)
    source_sha = git("rev-parse", "HEAD", cwd=source)
    image_tag = f"{tag[1:]}-yeap.{revision}" if tag else f"sha-{source_sha}"
    metadata = {
        "upstream_tag": tag or None,
        "source_sha": source_sha,
        "fork_sha": os.environ["GITHUB_SHA"],
        "fork_base_sha": base,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "build_revision": revision,
        "features": features,
        "omitted_features": omitted,
        "image": f"ghcr.io/{os.environ['GITHUB_REPOSITORY'].lower()}",
        "image_tag": image_tag,
    }
    destination = Path(os.environ["RUNNER_TEMP"]) / "fork-build"
    destination.mkdir(exist_ok=True)
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (destination / "fork.patch").write_bytes(patch)
    outputs({**{k: v for k, v in metadata.items() if isinstance(v, str)}, "source": source})
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "upgrade", "features", "fetch-base"])
    parser.add_argument("--tag", default="")
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "upgrade":
        upgrade(args.tag, args.source)
    elif args.command == "features":
        print(public_features(args.source)[0])
    elif args.command == "fetch-base":
        fetch_base(ROOT)
    else:
        prepare()

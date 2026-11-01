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
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = "windmill-labs/windmill"


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def stable_tag(value):
    if not re.fullmatch(r"v\d+\.\d+\.\d+", value):
        raise ValueError(f"Expected a stable upstream release tag, got {value!r}")
    return value


def patches(root):
    result = sorted((root / "fork/patches").glob("*.patch"))
    if not result:
        raise ValueError("No fork patches found")
    return result


def build_revision(root):
    files = patches(root) + [
        root / ".github/scripts/fork_build.py",
        root / ".github/scripts/smoke_image.py",
        root / ".github/workflows/fork-image.yml",
    ]
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:12]


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


def apply_patches(source, root):
    for patch in patches(root):
        git("apply", "--check", str(patch), cwd=source)
        git("apply", str(patch), cwd=source)


def api(path):
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def outputs(values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        for key, value in values.items():
            if "\n" in str(value) or "\r" in str(value):
                raise ValueError("Multiline workflow output")
            output.write(f"{key}={value}\n")


def select_release(tag):
    endpoint = f"releases/tags/{stable_tag(tag)}" if tag else "releases/latest"
    release = api(f"repos/{UPSTREAM}/{endpoint}")
    if release["draft"] or release["prerelease"]:
        raise ValueError("Only published stable upstream releases are supported")
    tag = stable_tag(release["tag_name"])
    release_tag = f"fork-{tag}-p{build_revision(ROOT)}"
    skip = "false"
    try:
        api(f"repos/{os.environ['GITHUB_REPOSITORY']}/releases/tags/{release_tag}")
        skip = "true"
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    outputs({"upstream_tag": tag, "release_tag": release_tag, "skip": skip})


def prepare(source, tag):
    if tag:
        stable_tag(tag)
        git("clone", "--depth", "1", "--branch", tag,
            f"https://github.com/{UPSTREAM}.git", str(source))
        apply_patches(source, ROOT)
    else:
        source = ROOT
    features, omitted = public_features(source)
    revision = build_revision(ROOT)
    source_sha = git("rev-parse", "HEAD", cwd=source)
    image_tag = f"{tag[1:]}-yeap.{revision}" if tag else f"sha-{source_sha}"
    metadata = {
        "upstream_tag": tag or None,
        "source_sha": source_sha,
        "fork_sha": os.environ["GITHUB_SHA"],
        "build_revision": revision,
        "features": features,
        "omitted_features": omitted,
        "image": f"ghcr.io/{os.environ['GITHUB_REPOSITORY'].lower()}",
        "image_tag": image_tag,
    }
    destination = Path(os.environ["RUNNER_TEMP"]) / "fork-build"
    destination.mkdir(exist_ok=True)
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (destination / "fork.patch").write_bytes(b"".join(p.read_bytes() for p in patches(ROOT)))
    outputs({**{k: v for k, v in metadata.items() if isinstance(v, str)}, "source": source})
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "release", "features"])
    parser.add_argument("--tag", default="")
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "release":
        select_release(args.tag)
    elif args.command == "features":
        print(public_features(args.source)[0])
    else:
        prepare(args.source, args.tag)

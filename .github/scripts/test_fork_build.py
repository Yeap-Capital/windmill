import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("fork_build", Path(__file__).with_name("fork_build.py"))
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
PATCH_BASE = BUILD.upstream_base(BUILD.ROOT)["sha"]
SOURCE_FILES = [path for path in subprocess.check_output(
    ["git", "diff", "--name-only", "--no-renames", "-z", PATCH_BASE, "HEAD", "--", *BUILD.PATCH_PATHS],
    cwd=BUILD.ROOT,
).decode().split("\0") if path]


def checkout_base_files(root):
    for path in SOURCE_FILES:
        original = subprocess.run(["git", "show", f"{PATCH_BASE}:{path}"],
                                  cwd=BUILD.ROOT, capture_output=True)
        if original.returncode == 0:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.stdout)


class ReleaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.patch = BUILD.generate_patch(BUILD.ROOT, PATCH_BASE)

    def test_public_ce_keeps_languages_and_authentication(self):
        selected, omitted = BUILD.public_features(BUILD.ROOT)
        self.assertTrue({"oss_core", "all_languages"} <= set(selected.split(",")))
        self.assertIn("private", omitted)

    def test_nested_auth_bypass_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            (root / "backend/Cargo.toml").write_text(
                '[features]\ndefault=[]\nce=["group"]\ngroup=["oss_core", "no_auth", "private"]\n'
                'oss_core=[]\nno_auth=[]\nprivate=[]\n'
            )
            self.assertEqual(BUILD.public_features(root), ("oss_core", ["no_auth", "private"]))

    def test_default_auth_bypass_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            (root / "backend/Cargo.toml").write_text(
                '[features]\ndefault=["no_auth"]\nce=["oss_core"]\noss_core=[]\nno_auth=[]\n'
            )
            with self.assertRaisesRegex(ValueError, "default features"):
                BUILD.public_features(root)

    def test_release_tag_rejects_refs_and_prereleases(self):
        self.assertEqual(BUILD.stable_tag("v1.855.1"), "v1.855.1")
        for value in ["main", "--help", "v1.855.1-rc.1", "v1.855.1\nextra"]:
            with self.assertRaises(ValueError):
                BUILD.stable_tag(value)

    def test_upgrade_refuses_a_non_main_workflow_before_api_access(self):
        with patch.dict("os.environ", {"GITHUB_REF": "refs/heads/unmerged-feature"}):
            with self.assertRaisesRegex(ValueError, "main workflow snapshot"):
                BUILD.upgrade("", Path("unused-worktree"))

    def test_patch_reproduces_fork_from_its_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            checkout_base_files(root)
            BUILD.apply_patch(root, self.patch)
            for path in SOURCE_FILES:
                # Compare behavior-bearing source, not workflow or test-only changes.
                if (BUILD.ROOT / path).exists():
                    self.assertEqual((root / path).read_bytes(), (BUILD.ROOT / path).read_bytes(), path)
                else:
                    self.assertFalse((root / path).exists(), path)
            if self.patch:
                with self.assertRaises(subprocess.CalledProcessError):
                    BUILD.apply_patch(root, self.patch)

    def test_conflict_does_not_partially_apply_a_patch(self):
        if not SOURCE_FILES:
            self.skipTest("Main has no production changes relative to upstream")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            checkout_base_files(root)
            changed = root / SOURCE_FILES[0]
            changed.parent.mkdir(parents=True, exist_ok=True)
            changed.write_text("conflicting upstream content\n")
            before = {path: (root / path).read_bytes() for path in SOURCE_FILES if (root / path).exists()}
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.apply_patch(root, self.patch)
            self.assertEqual(before, {path: (root / path).read_bytes() for path in SOURCE_FILES if (root / path).exists()})

    def test_release_rebase_preserves_main_changes_and_new_upstream_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            BUILD.git("config", "user.email", "test@example.com", cwd=root)
            BUILD.git("config", "user.name", "Test", cwd=root)
            (root / "feature.txt").write_text("original\n")
            BUILD.git("add", ".", cwd=root)
            BUILD.git("commit", "-qm", "upstream base", cwd=root)
            base = BUILD.git("rev-parse", "HEAD", cwd=root)
            (root / "upstream-only.txt").write_text("new official code\n")
            BUILD.git("add", ".", cwd=root)
            BUILD.git("commit", "-qm", "upstream advance", cwd=root)
            BUILD.git("branch", "official-main", cwd=root)
            BUILD.git("checkout", "-q", "--detach", base, cwd=root)
            (root / "feature.txt").write_text("our feature\n")
            (root / ".github").mkdir()
            (root / ".github/workflow.yml").write_text("fork build tooling\n")
            (root / BUILD.BASE_FILE).write_text(json.dumps({"sha": base, "tag": None}))
            BUILD.git("add", ".", cwd=root)
            BUILD.git("commit", "-qm", "fork main changes", cwd=root)
            actual_base, patch = BUILD.generate_patch(root)
            self.assertEqual(actual_base, base)
            self.assertIn(b"our feature", patch)
            self.assertNotIn(b"upstream-only", patch)
            self.assertNotIn(b".github", patch)
            main_sha = BUILD.git("rev-parse", "HEAD", cwd=root)
            target = BUILD.git("rev-parse", "official-main", cwd=root)
            source = root / "upgrade-worktree"
            commit = BUILD.rebase_main(root, source, "v1.999.0", target)
            self.assertEqual((source / "feature.txt").read_text(), "our feature\n")
            self.assertEqual((source / "upstream-only.txt").read_text(), "new official code\n")
            self.assertEqual((source / ".github/workflow.yml").read_text(), "fork build tooling\n")
            self.assertEqual(BUILD.upstream_base(source), {"sha": target, "tag": "v1.999.0"})
            self.assertEqual(BUILD.git("rev-parse", "HEAD", cwd=root), main_sha)
            parents = BUILD.git("rev-list", "--parents", "-n", "1", commit, cwd=root).split()
            self.assertEqual(parents[1:], [main_sha, target])
            # Squash-merging this tree must still leave the next fork patch free of upstream code.
            BUILD.git("read-tree", f"{commit}^{{tree}}", cwd=root)
            BUILD.git("checkout-index", "--all", "--force", cwd=root)
            BUILD.git("commit", "-qm", "squashed upgrade PR", cwd=root)
            _, next_patch = BUILD.generate_patch(root)
            self.assertIn(b"our feature", next_patch)
            self.assertNotIn(b"upstream-only", next_patch)


if __name__ == "__main__":
    unittest.main()

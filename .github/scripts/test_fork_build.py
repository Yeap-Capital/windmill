import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location("fork_build", Path(__file__).with_name("fork_build.py"))
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)
SOURCE_FILES = [
    "backend/windmill-api-workspaces/src/workspaces.rs",
    "frontend/src/lib/components/sessions/WorkspaceFamilyPicker.svelte",
    "frontend/src/lib/components/sessions/sessionState.svelte.ts",
]
PATCH_BASE = "5f68eb9f4479bf209a34a34c857dd1d7e8de0eb9"


class ReleaseBuildTests(unittest.TestCase):
    def test_public_ce_keeps_languages_and_authentication(self):
        selected, omitted = BUILD.public_features(BUILD.ROOT)
        self.assertEqual(set(selected.split(",")), {
            "oss_core", "operator", "all_languages", "jemalloc", "dind", "agent_worker_server",
        })
        self.assertEqual(omitted, ["private"])

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

    def test_patch_reproduces_fork_from_its_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            for path in SOURCE_FILES:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(
                    ["git", "show", f"{PATCH_BASE}:{path}"], cwd=BUILD.ROOT,
                ))
            BUILD.apply_patches(root, BUILD.ROOT)
            for path in SOURCE_FILES:
                # Compare behavior-bearing source, not workflow or test-only changes.
                self.assertEqual((root / path).read_bytes(), (BUILD.ROOT / path).read_bytes(), path)
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.apply_patches(root, BUILD.ROOT)

    def test_patch_applies_to_supported_upstream_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            for path in SOURCE_FILES:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(
                    ["git", "show", f"v1.855.1:{path}"], cwd=BUILD.ROOT,
                ))
            BUILD.apply_patches(root, BUILD.ROOT)
            self.assertNotIn("_check_nb_of_workspaces", (root / SOURCE_FILES[0]).read_text())
            self.assertNotIn("_check_nb_of_archived_workspaces", (root / SOURCE_FILES[0]).read_text())
            for path in SOURCE_FILES[1:]:
                self.assertNotIn("CE_MAX_NON_ADMIN_WORKSPACES", (root / path).read_text())

    def test_conflict_does_not_partially_apply_a_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", directory], check=True)
            for path in SOURCE_FILES:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(
                    ["git", "show", f"v1.855.1:{path}"], cwd=BUILD.ROOT,
                ))
            changed = root / SOURCE_FILES[0]
            changed.write_text(changed.read_text().replace("_check_nb_of_workspaces", "upstream_changed"))
            before = {path: (root / path).read_bytes() for path in SOURCE_FILES}
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.apply_patches(root, BUILD.ROOT)
            self.assertEqual(before, {path: (root / path).read_bytes() for path in SOURCE_FILES})


if __name__ == "__main__":
    unittest.main()

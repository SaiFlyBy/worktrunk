"""Verify explicit and generated CI jobs exclude macOS without dropping product targets."""
import copy
import importlib.util
from pathlib import Path
import re
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ci_dist_plan", ROOT / ".github/tools/verify_ci_dist_plan.py")
plan_policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan_policy)


def validate_static_workflow(source):
    # No workflow needs a macOS scheduling literal. Cover scalar, inline and
    # block lists, including self-hosted labels and matrix values.
    for line in source.splitlines():
        if not line.lstrip().startswith("#") and re.search(r"(?i)\bmacos(?:-[\w.]+)?\b", line):
            raise ValueError("workflow contains a macOS scheduling literal")


class CiPlatformTests(unittest.TestCase):
    def test_static_jobs_and_shared_setup_have_no_macos_runners(self):
        for path in (ROOT / ".github/workflows").iterdir():
            if path.suffix in {".yaml", ".yml"}:
                validate_static_workflow(path.read_text(encoding="utf-8"))
        for source in ("runs-on: macos-26", "runs-on: [self-hosted, macOS]",
                       "os: [ubuntu-24.04, macos-26]", "runs-on:\n  - self-hosted\n  - macOS"):
            with self.assertRaises(ValueError):
                validate_static_workflow(source)
        setup = (ROOT / ".github/actions/test-setup/action.yaml").read_text(encoding="utf-8")
        self.assertNotIn("runner.os == 'macOS'", setup)
        release = (ROOT / ".github/workflows/release.yaml").read_text(encoding="utf-8")
        for target in plan_policy.TARGETS:
            self.assertIn("--target=" + target, release)
        for line in release.splitlines():
            if re.search(r"^\s+dist (?:\$\{|build |host )", line) and "matrix.dist_args" not in line:
                self.assertIn("${{ env.DIST_CI_TARGETS }}", line)
        self.assertIn("python3 .github/tools/verify_ci_dist_plan.py plan-dist-manifest.json", release)

    def test_generated_plan_rejects_macos_unknown_missing_and_duplicate_targets(self):
        rows = [{"runner": "windows-2022" if "windows" in target else "ubuntu-22.04", "targets": [target],
                 "dist_args": "--artifacts=local --target=" + target}
                for target in sorted(plan_policy.TARGETS)]
        valid = {"ci": {"github": {"artifacts_matrix": {"include": rows}}}}
        plan_policy.validate(valid)
        for mutate in (lambda r: r.append({"runner": "macos-26", "targets": ["aarch64-apple-darwin"]}),
                       lambda r: r[0].update(runner="macos-26"), lambda r: r.pop(),
                       lambda r: r.append(copy.deepcopy(r[0])),
                       lambda r: r[0].update(dist_args="--artifacts=local --target=aarch64-apple-darwin")):
            candidate = copy.deepcopy(valid)
            mutate(candidate["ci"]["github"]["artifacts_matrix"]["include"])
            with self.assertRaises(ValueError):
                plan_policy.validate(candidate)

    def test_product_targets_still_include_both_apple_architectures(self):
        config = tomllib.loads((ROOT / "dist-workspace.toml").read_text(encoding="utf-8"))
        self.assertTrue({"aarch64-apple-darwin", "x86_64-apple-darwin"} <= set(config["dist"]["targets"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)

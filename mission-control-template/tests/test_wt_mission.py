"""Behavioral tests for the scope-at-a-time Worktrunk bridge."""
from __future__ import annotations

import contextlib
import concurrent.futures
import threading
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "wt_mission", Path(__file__).resolve().parents[1] / "tools" / "wt_mission.py"
)
bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bridge)


class SettlementCompatibilityTests(unittest.TestCase):
    def test_unsupported_frozen_runtime_reports_the_missing_reconciliation_capability(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-old-runtime-") as temp:
            root = Path(temp) / "mission"
            runtime = root / "runtime" / "tools" / "mc.py"
            runtime.parent.mkdir(parents=True)
            runtime.write_text(
                "import sys\nif __name__ == '__main__':\n"
                "    print('settlement failed', file=sys.stderr)\n    sys.exit(1)\n",
                encoding="utf-8",
            )
            evidence = []
            for name in ("result", "receipt", "adjudication"):
                path = root / f"{name}.json"
                path.write_text("{}", encoding="utf-8")
                evidence.append(path)
            proc = subprocess.run(
                [bridge.sys.executable, str(Path(bridge.__file__)), "settle",
                 "--root", str(root), "--cell", "A000", "--attempt", "1",
                 "--result", str(evidence[0]), "--context-receipt", str(evidence[1]),
                 "--adjudication", str(evidence[2]), "--reconcile"],
                capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, proc.returncode)
            self.assertIn("unsupported frozen mission runtime", proc.stderr)


class PublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = "a" * 40
        self.head = "b" * 40
        self.report = {
            "state": "ACCEPTED", "kind": "MUTATION",
            "target": {"repository": "owner/repo", "base_sha": self.base},
            "result": {"target_outcomes": [{
                "repository": "owner/repo", "baseline_sha": self.base, "head_sha": self.head,
            }]},
            "workspace": {"path": "/workspace", "branch": "scope/one", "clean": True,
                          "head_sha": self.head, "origin": "https://github.com/owner/repo.git"},
        }
        self.args = bridge.argparse.Namespace(root="/mission", cell="M000", base="main",
                                              title="Scope one", body="Evidence", gh="gh")
        self.calls: list[list[str]] = []
        self.remote_branch = None
        self.remote_base = self.base
        self.push_fails = False
        self.gh_fails = False
        self.base_queries = 0
        self.change_base_after_push = False
        self.advanced_base_in_head = False
        self.open_prs: list[dict] = []
        self.push_urls = ["https://github.com/owner/repo.git"]
        self.push_env = None

    def run_command(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[-5:] == ["remote", "get-url", "--push", "--all", "origin"]:
            return subprocess.CompletedProcess(argv, 0, "\n".join(self.push_urls) + "\n", "")
        if ("merge-base" in argv and self.remote_base != self.base and self.remote_base in argv
                and not self.advanced_base_in_head):
            return subprocess.CompletedProcess(argv, 1, "", "")
        if "push" in argv:
            self.push_env = kwargs.get("env")
            if self.push_fails:
                return subprocess.CompletedProcess(argv, 1, "", "unknown push result")
            self.remote_branch = self.head
        if "list" in argv and "pr" in argv:
            if self.gh_fails:
                return subprocess.CompletedProcess(argv, 1, "", "forge unavailable")
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.open_prs), "")
        if "view" in argv and "pr" in argv:
            value = {"url": argv[3], "headRefOid": self.head, "baseRefOid": self.remote_base,
                     "headRefName": "scope/one", "baseRefName": "main", "state": "OPEN",
                     "isDraft": True, "isCrossRepository": False}
            return subprocess.CompletedProcess(argv, 0, json.dumps(value), "")
        if "create" in argv and "pr" in argv:
            return subprocess.CompletedProcess(argv, 0, "https://github.com/owner/repo/pull/1\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def remote(self, repo, ref):
        if ref == "refs/heads/main":
            self.base_queries += 1
            return "d" * 40 if self.change_base_after_push and self.base_queries > 1 else self.remote_base
        return self.remote_branch

    def invoke(self):
        with patch.object(bridge, "read_json", return_value={"assets": {}}), \
             patch.object(bridge, "scope_report", return_value=self.report), \
             patch.object(bridge, "ledger_entry", return_value={
                 "branch": "scope/one", "remote_url": "https://github.com/owner/repo.git",
                 "repository": "owner/repo", "base_sha": self.base}), \
             patch.object(bridge, "remote_head", side_effect=self.remote), \
             patch.object(bridge, "run", side_effect=self.run_command), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            bridge.publish(self.args)
            return json.loads(out.getvalue())

    def test_accepted_head_is_created_with_absence_lease_and_draft_pr_is_opened(self):
        result = self.invoke()
        self.assertEqual(result["state"], "DRAFT_PR_CREATED")
        push = next(call for call in self.calls if "push" in call)
        self.assertIn(self.head + ":refs/heads/scope/one", push)
        self.assertIn("--force-with-lease=refs/heads/scope/one:", push)
        self.assertIn("remote.origin.mirror=false", push)
        self.assertIn("remote.origin.pushurl=", push)
        self.assertIn("--config-env=remote.origin.pushurl=WT_MISSION_PUSH_URL", push)
        self.assertEqual(self.push_env["WT_MISSION_PUSH_URL"], self.push_urls[0])
        self.assertNotIn(self.push_urls[0], push)
        self.assertIn("origin", push)
        self.assertIn("--no-follow-tags", push)
        self.assertIn("--recurse-submodules=no", push)
        self.assertNotIn("--force", push)
        self.assertFalse(any(part.startswith("+") for part in push))
        pr = next(call for call in self.calls if "create" in call and "pr" in call)
        self.assertIn("--draft", pr)
        self.assertEqual(result["base_sha"], self.base)

    def test_foreign_push_url_is_rejected_before_any_network(self):
        for urls in (["https://attacker.invalid/owner/repo.git"],
                     ["https://github.com/owner/repo.git", "https://attacker.invalid/owner/repo.git"],
                     ["https://github.com/owner/other.git"]):
            with self.subTest(urls=urls):
                self.push_urls = urls
                with self.assertRaisesRegex(bridge.BridgeError, "push destination"):
                    self.invoke()
                self.assertFalse(any("push" in call or "pr" in call for call in self.calls))
                self.calls.clear()

    def test_push_url_change_after_pr_lookup_is_rejected_before_upload(self):
        original = self.run_command
        def change_destination(argv, **kwargs):
            result = original(argv, **kwargs)
            if "pr" in argv and "list" in argv:
                self.push_urls = ["https://attacker.invalid/owner/repo.git"]
            return result
        self.run_command = change_destination
        with self.assertRaisesRegex(bridge.BridgeError, "push destination"):
            self.invoke()
        self.assertFalse(any("push" in call or ("pr" in call and "create" in call) for call in self.calls))

    def test_git_config_inspection_failure_blocks_before_push(self):
        original = self.run_command
        def fail_inspection(argv, **kwargs):
            if "--show-scope" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 1, "", "configuration unavailable")
            return original(argv, **kwargs)
        self.run_command = fail_inspection
        with self.assertRaisesRegex(bridge.BridgeError, "Cannot inspect Git configuration"):
            self.invoke()
        self.assertFalse(any("push" in call or ("pr" in call and "create" in call) for call in self.calls))

    def test_push_error_does_not_disclose_destination_credentials(self):
        secret_url = "https://secret-token@github.com/owner/repo.git"
        self.push_urls = [secret_url]
        original = self.run_command
        def fail_push(argv, **kwargs):
            if "push" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 1, "", "cannot reach " + secret_url)
            return original(argv, **kwargs)
        self.run_command = fail_push
        with self.assertRaises(bridge.BridgeError) as raised:
            self.invoke()
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertIn("reconcile", str(raised.exception))

    def test_unsupported_pushurl_reset_blocks_before_upload(self):
        original = self.run_command
        def old_git(argv, **kwargs):
            if "remote.origin.pushurl=wt-mission-binding-probe" in argv:
                self.calls.append(argv)
                return subprocess.CompletedProcess(argv, 0, "wt-mission-binding-probe\n" + self.push_urls[0] + "\n", "")
            return original(argv, **kwargs)
        self.run_command = old_git
        with self.assertRaisesRegex(bridge.BridgeError, "Git cannot safely bind"):
            self.invoke()
        self.assertFalse(any("push" in call or ("pr" in call and "create" in call) for call in self.calls))

    def test_changed_base_blocks_before_push(self):
        self.remote_base = "c" * 40
        with self.assertRaisesRegex(bridge.BridgeError, "remote base is contained"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_advanced_base_already_in_accepted_head_can_publish(self):
        self.remote_base = "c" * 40
        self.advanced_base_in_head = True
        result = self.invoke()
        self.assertEqual(result["state"], "DRAFT_PR_CREATED")
        self.assertEqual(result["base_sha"], self.remote_base)
        self.assertEqual(result["compiled_base_sha"], self.base)

    def test_dirty_or_changed_workspace_blocks_before_network(self):
        for field, value in (("clean", False), ("head_sha", "c" * 40)):
            with self.subTest(field=field):
                self.report["workspace"][field] = value
                with self.assertRaisesRegex(bridge.BridgeError, "Workspace"):
                    self.invoke()
                self.assertEqual(self.calls, [])
                self.report["workspace"][field] = True if field == "clean" else self.head

    def test_foreign_remote_branch_is_not_overwritten(self):
        self.remote_branch = "c" * 40
        with self.assertRaisesRegex(bridge.BridgeError, "different commit"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_uncertain_push_does_not_create_pr(self):
        self.push_fails = True
        with self.assertRaisesRegex(bridge.BridgeError, "reconcile"):
            self.invoke()
        self.assertFalse(any("create" in call for call in self.calls))

    def test_forge_lookup_failure_happens_before_push(self):
        self.gh_fails = True
        with self.assertRaisesRegex(bridge.BridgeError, "PR lookup failed"):
            self.invoke()
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_base_moving_during_push_preserves_branch_without_pr(self):
        self.change_base_after_push = True
        with self.assertRaisesRegex(bridge.BridgeError, "base changed after push"):
            self.invoke()
        self.assertEqual(self.remote_branch, self.head)
        self.assertFalse(any("create" in call for call in self.calls))

    def test_existing_matching_pr_is_returned_without_duplicate(self):
        self.remote_branch = self.head
        self.open_prs = [{"number": 8, "url": "https://github.com/owner/repo/pull/8",
                          "headRefOid": self.head}]
        result = self.invoke()
        self.assertEqual(result["state"], "EXISTING_PR")
        self.assertFalse(any("push" in call or "create" in call for call in self.calls))

    def test_unaccepted_scope_and_wrong_origin_are_rejected(self):
        self.report["state"] = "DISPATCHED"
        with self.assertRaisesRegex(bridge.BridgeError, "independently accepted"):
            self.invoke()
        self.report["state"] = "ACCEPTED"
        self.report["workspace"]["origin"] = "https://github.com/other/repo.git"
        with self.assertRaisesRegex(bridge.BridgeError, "Workspace custody"):
            self.invoke()
        self.assertEqual(self.calls, [])


    def test_post_create_metadata_must_bind_the_accepted_candidate(self):
        original = self.run_command
        for field, value in (("headRefOid", "c" * 40), ("baseRefOid", "d" * 40),
                             ("headRefName", "other"), ("baseRefName", "other"),
                             ("state", "CLOSED"), ("isDraft", False),
                             ("isCrossRepository", True), ("url", None)):
            with self.subTest(field=field):
                self.calls.clear()
                self.remote_branch = None
                def changed_view(argv, **kwargs):
                    proc = original(argv, **kwargs)
                    if "pr" in argv and "view" in argv:
                        data = json.loads(proc.stdout)
                        data[field] = value
                        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
                    return proc
                self.run_command = changed_view
                with self.assertRaisesRegex(bridge.BridgeError, "reconcile before retrying"):
                    self.invoke()
                self.assertEqual(self.remote_branch, self.head)
                self.assertEqual(sum("create" in call for call in self.calls), 1)
        self.run_command = original

    def test_uncertain_post_create_read_never_reports_success_or_retries(self):
        original = self.run_command
        for response in (subprocess.CompletedProcess([], 1, "", "unavailable"),
                         subprocess.CompletedProcess([], 0, "not json", ""),
                         subprocess.CompletedProcess([], 0, "[]", "")):
            with self.subTest(response=response):
                self.calls.clear()
                self.remote_branch = None
                def failed_view(argv, **kwargs):
                    proc = original(argv, **kwargs)
                    return response if "pr" in argv and "view" in argv else proc
                self.run_command = failed_view
                with self.assertRaisesRegex(bridge.BridgeError, "reconcile before retrying"):
                    self.invoke()
                self.assertEqual(sum("create" in call for call in self.calls), 1)
                self.assertEqual(self.remote_branch, self.head)
        self.run_command = original

    def test_refs_moving_after_forge_read_are_detected_for_new_and_existing_pr(self):
        original = self.run_command
        for existing in (False, True):
            for changed in ("head", "base"):
                with self.subTest(existing=existing, changed=changed):
                    self.calls.clear()
                    self.remote_base = self.base
                    self.remote_branch = self.head if existing else None
                    self.open_prs = ([{"number": 8, "url": "https://github.com/owner/repo/pull/8",
                                       "headRefOid": self.head}] if existing else [])
                    def race(argv, **kwargs):
                        proc = original(argv, **kwargs)
                        if "pr" in argv and "view" in argv:
                            if changed == "head":
                                self.remote_branch = "c" * 40
                            else:
                                self.remote_base = "d" * 40
                        return proc
                    self.run_command = race
                    with self.assertRaisesRegex(bridge.BridgeError, "remote refs changed"):
                        self.invoke()
                    self.assertEqual(sum("create" in call for call in self.calls), 0 if existing else 1)
        self.run_command = original

    def test_existing_pr_review_state_is_preserved(self):
        self.remote_branch = self.head
        self.open_prs = [{"number": 8, "url": "https://github.com/owner/repo/pull/8",
                          "headRefOid": self.head}]
        original = self.run_command
        def ready_pr(argv, **kwargs):
            proc = original(argv, **kwargs)
            if "pr" in argv and "view" in argv:
                data = json.loads(proc.stdout)
                data["isDraft"] = False
                return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
            return proc
        self.run_command = ready_pr
        result = self.invoke()
        self.assertEqual(result["state"], "EXISTING_PR")
        self.assertFalse(result["verified_pr"]["isDraft"])
        self.assertFalse(any("push" in call or "create" in call or "ready" in call for call in self.calls))

    def test_post_create_process_failure_requires_reconciliation(self):
        original = self.run_command
        def cannot_start(argv, **kwargs):
            if "pr" in argv and "view" in argv:
                raise bridge.BridgeError("Cannot start gh")
            return original(argv, **kwargs)
        self.run_command = cannot_start
        with self.assertRaisesRegex(bridge.BridgeError, "reconcile before retrying"):
            self.invoke()
        self.assertEqual(self.remote_branch, self.head)
        self.assertEqual(sum("create" in call for call in self.calls), 1)

    def test_final_remote_read_failure_requires_reconciliation(self):
        original = self.remote
        def unreadable(repo, ref):
            if any("view" in call for call in self.calls):
                raise bridge.BridgeError("remote unavailable")
            return original(repo, ref)
        self.remote = unreadable
        with self.assertRaisesRegex(bridge.BridgeError, "remote refs could not be read"):
            self.invoke()
        self.assertEqual(self.remote_branch, self.head)
        self.assertEqual(sum("create" in call for call in self.calls), 1)

    def test_unexpected_create_url_is_not_followed(self):
        original = self.run_command
        def wrong_url(argv, **kwargs):
            proc = original(argv, **kwargs)
            if "pr" in argv and "create" in argv:
                return subprocess.CompletedProcess(argv, 0, "https://example.invalid/pull/1", "")
            return proc
        self.run_command = wrong_url
        with self.assertRaisesRegex(bridge.BridgeError, "unexpected PR URL"):
            self.invoke()
        self.assertFalse(any("view" in call for call in self.calls))

class OriginTests(unittest.TestCase):
    def test_child_environment_drops_git_discovery_but_preserves_other_settings(self):
        source = {"GIT_DIR": "elsewhere", "GIT_WORK_TREE": "elsewhere",
                  "GIT_COMMON_DIR": "elsewhere", "GIT_INDEX_FILE": "elsewhere",
                  "GIT_OBJECT_DIRECTORY": "elsewhere", "WORKTRUNK_DIRECTIVE_CD_FILE": "elsewhere",
                  "GIT_CONFIG_COUNT": "1", "PATH": "retained"}
        child = bridge.child_environment(source)
        self.assertEqual(child, {"GIT_CONFIG_COUNT": "1", "PATH": "retained"})
        self.assertIn("GIT_DIR", source)

    def test_standard_origins_are_bound_to_repository(self):
        self.assertTrue(bridge.origin_matches("git@github.com:owner/repo.git", "owner/repo"))
        self.assertTrue(bridge.origin_matches("https://github.com/owner/repo", "owner/repo"))
        self.assertFalse(bridge.origin_matches("https://github.com/owner/other", "owner/repo"))
        self.assertFalse(bridge.origin_matches("C:/some/local/repo", "owner/repo"))


    def test_github_identity_rejects_encoded_and_path_like_repositories(self):
        self.assertTrue(bridge.github_origin("https://github.com/owner/repo.git", "owner/repo"))
        self.assertTrue(bridge.github_origin("git@github.com:owner/repo.git", "owner/repo"))
        self.assertTrue(bridge.github_origin("ssh://git@github.com/owner/repo.git", "owner/repo"))
        for repository in ("owner/repo/../other", "owner/..", "owner/%2e%2e",
                           "owner/repo%2fother", "owner/repo\\..\\other", "owner/repo?query"):
            with self.subTest(repository=repository):
                self.assertFalse(bridge.github_origin("https://github.com/" + repository + ".git", repository))
        self.assertFalse(bridge.github_origin("https://github.com/owner/repo.git?redirect=other", "owner/repo"))
        self.assertFalse(bridge.github_origin("https://github.com/owner/repo.git#fragment", "owner/repo"))


class EffectivePushDestinationTests(unittest.TestCase):
    """Exercise Git's actual multiple-pushurl and URL-rewrite resolution."""

    def test_git_expands_and_checks_all_effective_push_urls(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-push-urls-") as tmp:
            repo = Path(tmp) / "repo"
            env = bridge.child_environment(os.environ)
            for key in list(env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    env.pop(key, None)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv):
                return subprocess.run(["git", *argv], check=True, capture_output=True, env=env,
                                      text=True, encoding="utf-8").stdout.strip()
            git_at("init", str(repo))
            git_at("-C", str(repo), "remote", "add", "origin", "https://github.com/owner/repo.git")
            with patch.dict(os.environ, env, clear=True):
                bridge.validate_push_destinations(repo, "owner/repo")
                git_at("-C", str(repo), "config", "--add", "remote.origin.pushurl", "https://github.com/owner/repo.git")
                git_at("-C", str(repo), "config", "--add", "remote.origin.pushurl", "git@github.com:owner/repo.git")
                bridge.validate_push_destinations(repo, "owner/repo")
                git_at("-C", str(repo), "config", "--add", "remote.origin.pushurl", "https://attacker.invalid/owner/repo.git")
                with self.assertRaisesRegex(bridge.BridgeError, "push destination"):
                    bridge.validate_push_destinations(repo, "owner/repo")
                git_at("-C", str(repo), "config", "--unset-all", "remote.origin.pushurl")
                git_at("-C", str(repo), "config", "url.https://attacker.invalid/.pushInsteadOf", "https://github.com/")
                with self.assertRaisesRegex(bridge.BridgeError, "push destination"):
                    bridge.validate_push_destinations(repo, "owner/repo")


class RealGitPublishTests(unittest.TestCase):
    """Use a disposable local Git remote and a simulated forge, never live GitHub."""

    def test_parallel_ref_publication_uses_per_ref_compare_and_swap(self):
        """Synchronize actual pushes, not sleeps: unrelated refs both succeed;
        two candidates for one absent ref have exactly one winner.
        """
        with tempfile.TemporaryDirectory(prefix="wt-mission-parallel-") as tmp:
            root = Path(tmp)
            (root / "TEMPLATE_LOCK.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
            bare, repo = root / "remote.git", root / "repo"
            env = bridge.child_environment(os.environ)
            for key in list(env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    env.pop(key, None)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv):
                return subprocess.run(["git", *argv], check=True, capture_output=True, env=env,
                                      text=True, encoding="utf-8", timeout=15).stdout.strip()
            git_at("init", "--bare", str(bare))
            git_at("init", "-b", "main", str(repo))
            git_at("-C", str(repo), "config", "user.name", "Fixture")
            git_at("-C", str(repo), "config", "user.email", "fixture@example.invalid")
            git_at("-C", str(repo), "commit", "--allow-empty", "-m", "first")
            first = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "commit", "--allow-empty", "-m", "second")
            second = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "remote", "add", "origin", str(bare))
            for refs in (("refs/heads/one", "refs/heads/two"),
                         ("refs/heads/shared", "refs/heads/shared")):
                with self.subTest(refs=refs):
                    barrier = threading.Barrier(2, timeout=5)
                    def bounded_run(argv, **kwargs):
                        if "push" in argv:
                            barrier.wait()
                        return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                                              timeout=15, **kwargs)
                    with patch.object(bridge, "child_environment", side_effect=lambda _: dict(env)), \
                         patch.object(bridge, "run", side_effect=bounded_run), \
                         concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                        futures = [pool.submit(bridge.push_to_verified_destination, repo, str(bare), oid, ref)
                                   for oid, ref in zip((first, second), refs)]
                        results = [future.result(timeout=20) for future in futures]
                    if refs[0] != refs[1]:
                        self.assertEqual([proc.returncode for proc in results], [0, 0])
                        for oid, ref in zip((first, second), refs):
                            self.assertEqual(git_at("--git-dir", str(bare), "rev-parse", ref), oid)
                    else:
                        winners = [i for i, proc in enumerate(results) if proc.returncode == 0]
                        self.assertEqual(len(winners), 1)
                        self.assertEqual(git_at("--git-dir", str(bare), "rev-parse", refs[0]),
                                         (first, second)[winners[0]])
            self.assertEqual(git_at("-C", str(repo), "rev-parse", "HEAD"), second)

    def test_publish_pushes_the_accepted_commit_to_a_real_git_remote(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-git-") as tmp:
            root = Path(tmp)
            (root / "TEMPLATE_LOCK.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
            bare, repo = root / "remote.git", root / "repo"
            test_env = bridge.child_environment(os.environ)
            for key in list(test_env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    test_env.pop(key, None)
            test_env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                             "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv):
                return subprocess.run(["git", *argv], check=True, capture_output=True, env=test_env,
                                      text=True, encoding="utf-8").stdout.strip()
            git_at("init", "--bare", str(bare))
            git_at("init", "-b", "main", str(repo))
            git_at("-C", str(repo), "config", "user.name", "Fixture")
            git_at("-C", str(repo), "config", "user.email", "fixture@example.invalid")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "tracked.txt")
            git_at("-C", str(repo), "commit", "-m", "base")
            base = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "remote", "add", "origin", str(bare))
            git_at("-C", str(repo), "push", "origin", "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "advance")
            (repo / "other.txt").write_text("accepted main\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "other.txt")
            git_at("-C", str(repo), "commit", "-m", "advance main")
            advanced_base = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "push", "origin", "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "scope/one", base)
            (repo / "tracked.txt").write_text("scope\n", encoding="utf-8")
            git_at("-C", str(repo), "commit", "-am", "one scope")
            git_at("-C", str(repo), "merge", "--no-edit", "advance")
            head = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "tag", "-a", "unrelated-tag", "-m", "must not be pushed")
            git_at("-C", str(repo), "config", "push.followTags", "true")
            git_at("-C", str(repo), "config", "remote.origin.mirror", "true")
            report = {
                "state": "ACCEPTED", "kind": "MUTATION",
                "target": {"repository": "owner/repo", "base_sha": base},
                "result": {"target_outcomes": [{"repository": "owner/repo",
                                                   "baseline_sha": base, "head_sha": head}]},
                # The real remote is local; the origin identity and forge are simulated here.
                "workspace": {"path": str(repo), "branch": "scope/one", "clean": True,
                              "head_sha": head, "origin": "https://github.com/owner/repo.git"},
            }
            args = bridge.argparse.Namespace(root=str(root), cell="M000", base="main",
                                             title="Scope", body="Evidence", gh="gh-fixture")
            real_run = bridge.run
            forge_calls = []
            def run_fixture(argv, **kwargs):
                if argv[0] == "gh-fixture":
                    forge_calls.append(argv)
                    output = "[]" if "list" in argv else "https://github.com/owner/repo/pull/1"
                    if "view" in argv:
                        output = json.dumps({"url": argv[3], "headRefOid": head,
                            "baseRefOid": advanced_base, "headRefName": "scope/one",
                            "baseRefName": "main", "state": "OPEN", "isDraft": True,
                            "isCrossRepository": False})
                    return subprocess.CompletedProcess(argv, 0, output, "")
                kwargs.setdefault("env", test_env)
                return real_run(argv, **kwargs)
            with patch.object(bridge, "scope_report", return_value=report), \
                 patch.object(bridge, "ledger_entry", return_value={
                     "branch": "scope/one", "remote_url": "https://github.com/owner/repo.git",
                     "repository": "owner/repo", "base_sha": base}), \
                 patch.object(bridge, "run", side_effect=run_fixture), \
                 patch.object(bridge, "validate_push_destinations", return_value=[str(bare)]), \
                 patch.dict(os.environ, test_env, clear=True), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                bridge.publish(args)
            published = json.loads(output.getvalue())
            self.assertEqual(published["state"], "DRAFT_PR_CREATED")
            self.assertEqual(published["base_sha"], advanced_base)
            self.assertEqual(published["compiled_base_sha"], base)
            self.assertEqual(git_at("--git-dir", str(bare), "rev-parse", "refs/heads/scope/one"), head)
            self.assertEqual(git_at("--git-dir", str(bare), "for-each-ref", "refs/tags"), "")
            self.assertTrue(any("create" in call and "--draft" in call for call in forge_calls))


    def test_concurrent_ancestor_branch_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-push-race-") as tmp:
            root = Path(tmp)
            (root / "TEMPLATE_LOCK.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
            bare, repo = root / "remote.git", root / "repo"
            env = bridge.child_environment(os.environ)
            for key in list(env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    env.pop(key, None)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv):
                return subprocess.run(["git", *argv], check=True, capture_output=True, env=env,
                                      text=True, encoding="utf-8").stdout.strip()
            git_at("init", "--bare", str(bare))
            git_at("init", "-b", "main", str(repo))
            git_at("-C", str(repo), "config", "user.name", "Fixture")
            git_at("-C", str(repo), "config", "user.email", "fixture@example.invalid")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "tracked.txt")
            git_at("-C", str(repo), "commit", "-m", "base")
            base = git_at("-C", str(repo), "rev-parse", "HEAD")
            git_at("-C", str(repo), "remote", "add", "origin", str(bare))
            git_at("-C", str(repo), "push", "origin", "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "scope/one")
            (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
            git_at("-C", str(repo), "commit", "-am", "candidate")
            head = git_at("-C", str(repo), "rev-parse", "HEAD")
            report = {"state": "ACCEPTED", "kind": "MUTATION",
                "target": {"repository": "owner/repo", "base_sha": base},
                "result": {"target_outcomes": [{"repository": "owner/repo", "baseline_sha": base, "head_sha": head}]},
                "workspace": {"path": str(repo), "branch": "scope/one", "clean": True,
                              "head_sha": head, "origin": "https://github.com/owner/repo.git"}}
            args = bridge.argparse.Namespace(root=str(root), cell="M000", base="main",
                                             title="Scope", body="Evidence", gh="gh-fixture")
            real_run = bridge.run
            calls = []
            def run_fixture(argv, **kwargs):
                calls.append(argv)
                if argv[0] == "gh-fixture":
                    return subprocess.CompletedProcess(argv, 0, "[]" if "list" in argv else "unexpected PR", "")
                if "push" in argv:
                    # Another actor creates an ancestor after the bridge's absence probe.
                    git_at("-C", str(repo), "push", "origin", f"{base}:refs/heads/scope/one")
                kwargs.setdefault("env", env)
                return real_run(argv, **kwargs)
            with patch.object(bridge, "scope_report", return_value=report), \
                 patch.object(bridge, "ledger_entry", return_value={"branch": "scope/one",
                     "remote_url": "https://github.com/owner/repo.git", "repository": "owner/repo", "base_sha": base}), \
                 patch.object(bridge, "validate_push_destinations", return_value=[str(bare)]), \
                 patch.object(bridge, "run", side_effect=run_fixture), \
                 patch.dict(os.environ, env, clear=True), \
                 contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(bridge.BridgeError, "reconcile"):
                    bridge.publish(args)
            self.assertEqual(git_at("--git-dir", str(bare), "rev-parse", "refs/heads/scope/one"), base)
            self.assertFalse(any(call[0] == "gh-fixture" and "create" in call for call in calls))
            push = next(call for call in calls if "push" in call)
            self.assertIn("--force-with-lease=refs/heads/scope/one:", push)
            self.assertNotIn("--force", push)


    def test_destination_is_bound_across_pushurl_change_and_second_rewrite(self):
        with tempfile.TemporaryDirectory(prefix="wt-mission-destination-race-") as tmp:
            root = Path(tmp)
            (root / "TEMPLATE_LOCK.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
            good, bad, repo = root / "good.git", root / "bad.git", root / "repo"
            good_url, bad_url = good.as_posix(), bad.as_posix()
            env = bridge.child_environment(os.environ)
            for key in list(env):
                if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                    env.pop(key, None)
            env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                        "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
            def git_at(*argv, check=True, git_env=None):
                return subprocess.run(["git", *argv], check=check, capture_output=True,
                                      env=git_env or env, text=True, encoding="utf-8")
            git_at("init", "--bare", str(good))
            git_at("init", "--bare", str(bad))
            git_at("init", "-b", "main", str(repo))
            git_at("-C", str(repo), "config", "user.name", "Fixture")
            git_at("-C", str(repo), "config", "user.email", "fixture@example.invalid")
            (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
            git_at("-C", str(repo), "add", "tracked.txt")
            git_at("-C", str(repo), "commit", "-m", "base")
            base = git_at("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
            git_at("-C", str(repo), "push", good_url, "HEAD:refs/heads/main")
            git_at("-C", str(repo), "switch", "-c", "scope/one")
            (repo / "tracked.txt").write_text("candidate\n", encoding="utf-8")
            git_at("-C", str(repo), "commit", "-am", "candidate")
            head = git_at("-C", str(repo), "rev-parse", "HEAD").stdout.strip()
            git_at("-C", str(repo), "remote", "add", "origin", "fixture:fetch")
            git_at("-C", str(repo), "config", f"url.{good_url}.insteadOf", "fixture:fetch")
            git_at("-C", str(repo), "config", "--add", f"url.{good_url}.insteadOf", "fixture:push")
            git_at("-C", str(repo), "config", "--add", f"url.{good_url}.insteadOf", "fixture:push-second")
            git_at("-C", str(repo), "config", "remote.origin.pushurl", "fixture:push")
            git_at("-C", str(repo), "config", "--add", "remote.origin.pushurl", "fixture:push-second")
            original_system = root / "system.gitconfig"
            original_system.write_text(
                f"[url {bridge.config_quote(bad_url)}]\n\tinsteadOf = {bridge.config_quote(good_url)}\n"
                "[http]\n\tlowSpeedLimit = 12345\n", encoding="utf-8")
            env.update({"GIT_CONFIG_NOSYSTEM": "0", "GIT_CONFIG_SYSTEM": str(original_system)})
            # A naive push of the already-resolved URL is rewritten a second time.
            probe = git_at("-C", str(repo), "push", "--dry-run", good_url,
                           "HEAD:refs/heads/probe")
            self.assertIn(bad_url, probe.stderr.replace("\\", "/"))
            self.assertEqual(git_at("-C", str(repo), "remote", "get-url", "--push", "--all", "origin").stdout.splitlines(),
                             [good_url, good_url])
            # Both fixtures are inert and live only in this disposable repo.
            # The hook records its actual arguments and enforces the origin
            # name; receivepack records real origin-specific transport use.
            hook_output, transport_output = root / "hook.txt", root / "transport.txt"
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.write_text("#!/bin/sh\n"
                            "printf '%s\\n' \"$1\" \"$2\" \"$PWD\" > \"$WT_MISSION_TEST_HOOK_OUTPUT\"\n"
                            "[ \"$1\" = origin ] || exit 37\n", encoding="utf-8")
            hook.chmod(hook.stat().st_mode | 0o111)
            transport = root / "receive-pack.sh"
            transport.write_text("#!/bin/sh\n"
                                 "printf '%s\\n' \"$1\" > \"$WT_MISSION_TEST_TRANSPORT_OUTPUT\"\n"
                                 "exec git receive-pack \"$@\"\n", encoding="utf-8")
            transport.chmod(transport.stat().st_mode | 0o111)
            # Git for Windows needs its shell to source the fixture here;
            # POSIX sh can execute the script directly and preserve argv.
            receivepack = f'. "{transport.as_posix()}"' if os.name == "nt" else transport.as_posix()
            git_at("-C", str(repo), "config", "remote.origin.receivepack", receivepack)
            git_at("-C", str(repo), "config", "remote.origin.proxy", "http://127.0.0.1:9")
            git_at("-C", str(repo), "config", "remote.origin.proxyAuthMethod", "basic")
            env.update({"WT_MISSION_TEST_HOOK_OUTPUT": str(hook_output),
                        "WT_MISSION_TEST_TRANSPORT_OUTPUT": str(transport_output)})
            accepting_hook = hook.read_text(encoding="utf-8")
            hook.write_text("#!/bin/sh\n"
                            "printf '%s\\n' \"$1\" > \"$WT_MISSION_TEST_HOOK_OUTPUT\"\n"
                            "exit 37\n", encoding="utf-8")
            with patch.dict(os.environ, env, clear=True):
                rejected = bridge.push_to_verified_destination(repo, good_url, head, "refs/heads/hook-rejected")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertTrue(hook_output.exists(), f"pre-push hook did not run: {rejected.stderr}")
            self.assertEqual(hook_output.read_text(encoding="utf-8").strip(), "origin")
            self.assertNotEqual(git_at("--git-dir", str(good), "rev-parse", "--verify",
                                      "refs/heads/hook-rejected", check=False).returncode, 0)
            hook.write_text(accepting_hook, encoding="utf-8")
            report = {"state": "ACCEPTED", "kind": "MUTATION",
                "target": {"repository": "owner/repo", "base_sha": base},
                "result": {"target_outcomes": [{"repository": "owner/repo", "baseline_sha": base, "head_sha": head}]},
                "workspace": {"path": str(repo), "branch": "scope/one", "clean": True,
                              "head_sha": head, "origin": good_url}}
            args = bridge.argparse.Namespace(root=str(root), cell="M000", base="main",
                                             title="Scope", body="Evidence", gh="gh-fixture")
            real_run = bridge.run
            seen = {"push": False, "system_setting": False, "origin_settings": False}
            def run_fixture(argv, **kwargs):
                if argv[0] == "gh-fixture":
                    output = "[]" if "list" in argv else "https://github.com/owner/repo/pull/1"
                    if "view" in argv:
                        output = json.dumps({"url": argv[3], "headRefOid": head,
                            "baseRefOid": base, "headRefName": "scope/one",
                            "baseRefName": "main", "state": "OPEN", "isDraft": True,
                            "isCrossRepository": False})
                    return subprocess.CompletedProcess(argv, 0, output, "")
                if "push" in argv:
                    seen["push"] = True
                    # Change the named origin after its final validation, before Git runs.
                    git_at("-C", str(repo), "config", "--add", "remote.origin.pushurl", bad_url)
                    self.assertIn("origin", argv)
                    self.assertNotIn(good_url, argv)
                    self.assertEqual(kwargs["env"]["WT_MISSION_PUSH_URL"], good_url)
                    setting = git_at("-C", str(repo), "config", "--get", "http.lowSpeedLimit", git_env=kwargs["env"])
                    seen["system_setting"] = setting.stdout.strip() == "12345"
                    proxy = git_at("-C", str(repo), "config", "--get", "remote.origin.proxy", git_env=kwargs["env"])
                    auth = git_at("-C", str(repo), "config", "--get", "remote.origin.proxyAuthMethod", git_env=kwargs["env"])
                    seen["origin_settings"] = (proxy.stdout.strip(), auth.stdout.strip()) == ("http://127.0.0.1:9", "basic")
                kwargs.setdefault("env", env)
                result = real_run(argv, **kwargs)
                if "push" in argv and result.returncode:
                    hook_state = hook_output.read_text(encoding="utf-8") if hook_output.exists() else "missing"
                    transport_state = transport_output.read_text(encoding="utf-8") if transport_output.exists() else "missing"
                    self.fail(f"disposable Git push failed: {result.stderr}; hook={hook_state}; transport={transport_state}")
                return result
            with patch.dict(os.environ, env, clear=True), \
                 patch.object(bridge, "scope_report", return_value=report), \
                 patch.object(bridge, "ledger_entry", return_value={"branch": "scope/one", "remote_url": good_url,
                     "repository": "owner/repo", "base_sha": base}), \
                 patch.object(bridge, "github_origin", side_effect=lambda url, repository: url == good_url), \
                 patch.object(bridge, "run", side_effect=run_fixture), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                bridge.publish(args)
            self.assertEqual(json.loads(output.getvalue())["state"], "DRAFT_PR_CREATED")
            self.assertEqual(seen, {"push": True, "system_setting": True, "origin_settings": True})
            hook_lines = hook_output.read_text(encoding="utf-8").splitlines()
            self.assertEqual(hook_lines[:2], ["origin", good_url])
            self.assertTrue(hook_lines[2].replace("\\", "/").endswith("/repo"))
            self.assertIn("good.git", transport_output.read_text(encoding="utf-8"))
            self.assertEqual(git_at("--git-dir", str(good), "rev-parse", "refs/heads/scope/one").stdout.strip(), head)
            self.assertNotEqual(git_at("--git-dir", str(bad), "rev-parse", "--verify", "refs/heads/scope/one", check=False).returncode, 0)


class HandoffTests(unittest.TestCase):
    """A real Git graph with a simulated already-settled Mission Control record."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wt-mission-handoff-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.mission, self.repo, self.source = root / "mission", root / "repo", root / "source"
        self.mission.mkdir()
        (self.mission / "TEMPLATE_LOCK.json").write_text(json.dumps({"assets": {}}), encoding="utf-8")
        self.env = bridge.child_environment(os.environ)
        for key in list(self.env):
            if key in {"GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"} or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_"):
                self.env.pop(key, None)
        self.env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                         "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0"})
        self.git("init", "-b", "main", str(self.repo))
        self.git("-C", str(self.repo), "config", "user.name", "Fixture")
        self.git("-C", str(self.repo), "config", "user.email", "fixture@example.invalid")
        (self.repo / "base.txt").write_text("base\n", encoding="utf8")
        self.git("-C", str(self.repo), "add", "base.txt")
        self.git("-C", str(self.repo), "commit", "-m", "base")
        self.base = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.git("-C", str(self.repo), "worktree", "add", "-b", "scope/one", str(self.source), self.base)
        (self.source / "scope.txt").write_text("scope\n", encoding="utf8")
        self.git("-C", str(self.source), "add", "scope.txt")
        self.git("-C", str(self.source), "commit", "-m", "accepted scope")
        self.head = self.git("-C", str(self.source), "rev-parse", "HEAD")
        (self.repo / "main change.txt").write_text("advanced\n", encoding="utf8")
        self.git("-C", str(self.repo), "add", "main change.txt")
        self.git("-C", str(self.repo), "commit", "-m", "advance main")
        self.advanced = self.git("-C", str(self.repo), "rev-parse", "HEAD")
        self.target = {"repository": "owner/repo", "base_sha": self.base, "owned_paths": ["scope.txt"]}
        self.cell = {"cell_id": "M000", "kind": "MUTATION", "dependencies": ["G000"],
                     "objective": "One complete scope", "acceptance": ["scope works"], "status": "PENDING",
                     "conflict_class": "write:scope", "resource_claims": ["scope-resource"],
                     "requirement_ids": ["R001"], "target": self.target,
                     "positive_verification": ["positive"], "negative_verification": ["negative"],
                     "rollback": "revert scope", "result_schema": "contracts/schemas/RESULT_SCHEMA.json"}
        self.record = {"state": "ACCEPTED", "attempt": 1}
        for kind in ("result", "context_receipt", "adjudication"):
            path = self.mission / (kind + ".json")
            path.write_text(json.dumps({"kind": kind}) + "\n", encoding="utf8")
            self.record[kind + "_ref"] = path.name
            self.record[kind + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.workspace = {"path": str(self.source), "branch": "scope/one", "clean": True,
                          "head_sha": self.head, "origin": "https://github.com/owner/repo.git"}
        self.report = {"target": self.target, "result": {"target_outcomes": [{"repository": "owner/repo",
                       "baseline_sha": self.base, "head_sha": self.head}]}, "workspace": self.workspace}
        self.entry = {"branch": "scope/one", "remote_url": self.workspace["origin"],
                      "repository": "owner/repo", "base_sha": self.base}
        self.packet = {"kind": "MUTATION", "target": self.target}
        self.args = bridge.argparse.Namespace(root=str(self.mission), cell="M000", successor="M002",
                                              frontier="F200", base_sha=self.advanced)
        self.compiled = []

    def git(self, *argv):
        return subprocess.run(["git", *argv], check=True, capture_output=True, env=self.env,
                              text=True, encoding="utf8").stdout.strip()

    def invoke(self):
        def compile_frontier(root, *argv):
            self.assertEqual(argv[0:2], ("compile", "--frontier"))
            self.compiled.append(json.loads(Path(argv[2]).read_text(encoding="utf8")))
            return ""
        with patch.dict(os.environ, self.env, clear=True), \
             patch.object(bridge, "cell_info", return_value=(self.cell, self.record, self.packet)), \
             patch.object(bridge, "scope_report", return_value=self.report), \
             patch.object(bridge, "ledger_entry", return_value=self.entry), \
             patch.object(bridge, "mc", side_effect=compile_frontier), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            bridge.handoff(self.args)
            return json.loads(out.getvalue())

    def test_successor_binds_original_evidence_and_base_changes(self):
        result = self.invoke()
        successor = self.compiled[0]["cells"][0]
        self.assertEqual(result["state"], "SUCCESSOR_COMPILED")
        self.assertEqual(result["source_head"], self.head)
        self.assertEqual(result["observed_base"], self.advanced)
        self.assertEqual(result["base_changed_paths"], ["main change.txt"])
        self.assertEqual(successor["target"], self.target)
        self.assertEqual(successor["resource_claims"], self.cell["resource_claims"])
        self.assertEqual(successor["requirement_ids"], self.cell["requirement_ids"])
        self.assertIn("M000", successor["dependencies"])
        self.assertTrue(set(self.cell["acceptance"] + bridge.HANDOFF_ACCEPTANCE) <= set(successor["acceptance"]))
        payload = json.loads(successor["objective"].split(bridge.HANDOFF_MARKER, 1)[1])
        self.assertEqual(payload["accepted_evidence"]["result"]["sha256"], self.record["result_sha256"])
        self.assertEqual(self.git("-C", str(self.source), "rev-parse", "HEAD"), self.head)
        self.assertEqual(self.git("-C", str(self.repo), "rev-parse", "HEAD"), self.advanced)

    def test_changed_source_or_tampered_evidence_is_rejected_before_compile(self):
        self.workspace["head_sha"] = self.advanced
        with self.assertRaisesRegex(bridge.BridgeError, "custody"):
            self.invoke()
        self.workspace["head_sha"] = self.head
        (self.mission / "result.json").write_text("tampered\n", encoding="utf8")
        with self.assertRaisesRegex(bridge.BridgeError, "evidence changed"):
            self.invoke()
        self.assertEqual(self.compiled, [])

    def test_handoff_rejects_unaccepted_or_already_contained_base(self):
        self.record["state"] = "DISPATCHED"
        with self.assertRaisesRegex(bridge.BridgeError, "independently accepted"):
            self.invoke()
        self.record["state"] = "ACCEPTED"
        self.args.base_sha = self.base
        with self.assertRaisesRegex(bridge.BridgeError, "already contains"):
            self.invoke()
        self.assertEqual(self.compiled, [])


if __name__ == "__main__":
    unittest.main()

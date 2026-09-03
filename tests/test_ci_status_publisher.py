"""Tests for tools/ci_status_publisher.py.

The publisher wraps `gh api` to post commit statuses. These tests
exercise the validation logic (no real `gh` call) so the script's
contract is locked in even if the GH REST API changes shape.
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

# Make tools/ importable as a namespace package.
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import tools.ci_status_publisher as csp  # noqa: E402


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class CiStatusPublisherTests(unittest.TestCase):
    def test_rejects_too_few_args(self) -> None:
        with mock.patch.object(sys, "argv", ["ci_status_publisher.py"]):
            self.assertEqual(csp.main(sys.argv), 2)
        with mock.patch.object(sys, "argv", ["ci_status_publisher.py", "success"]):
            self.assertEqual(csp.main(sys.argv), 2)

    def test_rejects_invalid_state(self) -> None:
        with mock.patch.object(
            sys, "argv", ["csp", "green", "ci/test", "ok"]
        ):
            self.assertEqual(csp.main(sys.argv), 2)

    def test_truncates_description_to_140(self) -> None:
        long_desc = "x" * 250
        captured: dict = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return _FakeCompleted()

        with mock.patch.dict(
            os.environ, {"GITHUB_SHA": "abc123", "GITHUB_REPOSITORY": "o/r"}
        ), mock.patch.object(sys, "argv", ["csp", "success", "ci/test", long_desc]), mock.patch.object(
            subprocess, "run", side_effect=fake_run
        ):
            self.assertEqual(csp.main(sys.argv), 0)
            desc_value = next(
                arg for arg in captured["cmd"] if arg.startswith("description=")
            )
            val = desc_value.split("=", 1)[1]
            self.assertEqual(len(val), 140)
            self.assertEqual(val, "x" * 140)

    def test_posts_via_gh_api_with_expected_flags(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return _FakeCompleted()

        with mock.patch.dict(
            os.environ,
            {"GITHUB_SHA": "deadbeef", "GITHUB_REPOSITORY": "JonasAbde/aie"},
        ), mock.patch.object(
            sys, "argv", ["csp", "failure", "ci/test (3.12)", "tests failed"]
        ), mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(csp.main(sys.argv), 0)
            cmd = captured["cmd"]
            self.assertEqual(cmd[0], "gh")
            self.assertEqual(cmd[1], "api")
            self.assertEqual(cmd[2], "repos/JonasAbde/aie/statuses/deadbeef")
            self.assertEqual(cmd[3], "-X")
            self.assertEqual(cmd[4], "POST")
            # Each -f key=value should be its own argv slot.
            kv_args = [arg for arg in cmd[5:] if "=" in arg]
            keys = [a.split("=", 1)[0] for a in kv_args]
            self.assertEqual(keys, ["state", "context", "description"])
            joined = " ".join(cmd)
            self.assertIn("state=failure", joined)
            self.assertIn("context=ci/test (3.12)", joined)

    def test_includes_target_url_when_provided(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return _FakeCompleted()

        with mock.patch.dict(
            os.environ,
            {
                "GITHUB_SHA": "abc",
                "GITHUB_REPOSITORY": "o/r",
                "CI_TARGET_URL": "https://example.invalid/run/123",
            },
        ), mock.patch.object(
            sys, "argv", ["csp", "success", "ci/lint", "lint clean"]
        ), mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(csp.main(sys.argv), 0)
            self.assertIn(
                "target_url=https://example.invalid/run/123", captured["cmd"]
            )

    def test_omits_target_url_when_absent(self) -> None:
        captured: dict = {}

        def fake_run(cmd, capture_output, text):
            captured["cmd"] = cmd
            return _FakeCompleted()

        env = {"GITHUB_SHA": "abc", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            sys, "argv", ["csp", "success", "ci/lint", "lint clean"]
        ), mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(csp.main(sys.argv), 0)
            for arg in captured["cmd"]:
                self.assertFalse(
                    arg.startswith("target_url="),
                    f"target_url should not be present, got: {captured['cmd']!r}",
                )

    def test_missing_required_env_exits_2(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            sys, "argv", ["csp", "success", "ci/test", "ok"]
        ):
            with self.assertRaises(SystemExit) as cm:
                csp.main(sys.argv)
            self.assertEqual(cm.exception.code, 2)

    def test_propagates_nonzero_rc_from_gh(self) -> None:
        def fake_run(cmd, capture_output, text):
            return _FakeCompleted(
                returncode=1, stderr="gh: not authenticated", stdout=""
            )

        with mock.patch.dict(
            os.environ, {"GITHUB_SHA": "x", "GITHUB_REPOSITORY": "o/r"}
        ), mock.patch.object(
            sys, "argv", ["csp", "success", "ci/test", "ok"]
        ), mock.patch.object(subprocess, "run", side_effect=fake_run):
            self.assertEqual(csp.main(sys.argv), 1)


if __name__ == "__main__":
    unittest.main()

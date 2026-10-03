"""Updater regression tests using disposable local Git repositories."""

import importlib.util
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


# Load only the updater; tests must not open the user's log/config files.
SOURCE = Path(__file__).resolve().parents[1] / "aiquotabar" / "update.py"
spec = importlib.util.spec_from_file_location("update_under_test", SOURCE)
update = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {
    "aiquotabar.config": types.SimpleNamespace(
        log=logging.getLogger("test.update"),
        LAUNCH_AGENT_LABEL="com.aiquotabar",
        LEGACY_LAUNCH_AGENT_LABEL="com.claudebar",
    ),
}):
    spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def git(self, repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def commit(self, repo, name):
        (repo / name).write_text(name)
        self.git(repo, "add", name)
        self.git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", name)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.origin = root / "origin"
        self.local = root / "local"
        self.origin.mkdir()
        self.git(self.origin, "init", "-q", "-b", "main")
        self.commit(self.origin, "base")
        self.git(root, "clone", "-q", str(self.origin), str(self.local))
        source_patch = patch.object(update, "__file__", str(self.local / "aiquotabar/update.py"))
        source_patch.start()
        self.addCleanup(source_patch.stop)

    def test_equal_does_not_update(self):
        self.assertFalse(update._check_and_apply_update())

    def test_local_ahead_does_not_report_phantom_update(self):
        self.commit(self.local, "local-fix")
        before = self.git(self.local, "rev-parse", "HEAD")
        self.assertFalse(update._check_and_apply_update())
        self.assertEqual(before, self.git(self.local, "rev-parse", "HEAD"))

    def test_remote_ahead_updates_once(self):
        self.commit(self.origin, "upstream-fix")
        self.assertTrue(update._check_and_apply_update())
        self.assertEqual(self.git(self.origin, "rev-parse", "HEAD"),
                         self.git(self.local, "rev-parse", "HEAD"))
        self.assertFalse(update._check_and_apply_update())

    def test_diverged_history_is_preserved(self):
        self.commit(self.local, "local-fix")
        self.commit(self.origin, "upstream-fix")
        before = self.git(self.local, "rev-parse", "HEAD")
        self.assertFalse(update._check_and_apply_update())
        self.assertEqual(before, self.git(self.local, "rev-parse", "HEAD"))

    def test_local_edits_are_not_stashed(self):
        self.commit(self.origin, "upstream-fix")
        (self.local / "base").write_text("unsaved work")
        self.assertFalse(update._check_and_apply_update())
        self.assertEqual((self.local / "base").read_text(), "unsaved work")
        self.assertEqual(self.git(self.local, "stash", "list"), "")

    def test_untracked_work_is_preserved(self):
        self.commit(self.origin, "upstream-fix")
        (self.local / "new-work").write_text("work")
        self.assertFalse(update._check_and_apply_update())
        self.assertTrue((self.local / "new-work").exists())

    def test_fetch_failure_does_not_update(self):
        self.git(self.local, "remote", "set-url", "origin", str(self.local / "missing"))
        self.assertFalse(update._check_and_apply_update())


class RestartTests(unittest.TestCase):
    def test_launchd_respawns_instead_of_exec(self):
        # The legacy label still runs until logout after the rename migration.
        for label in ("com.aiquotabar", "com.claudebar"):
            with self.subTest(label=label), \
                    patch.dict(update.os.environ, {"XPC_SERVICE_NAME": label}), \
                    patch.object(update.os, "_exit", side_effect=SystemExit) as exit_call, \
                    patch.object(update.os, "execv") as exec_call, \
                    patch.object(update.subprocess, "Popen") as spawn:
                with self.assertRaises(SystemExit):
                    update._restart_app()
                exit_call.assert_called_once_with(75)
                exec_call.assert_not_called()
                spawn.assert_not_called()

    def test_manual_restart_spawns_new_process(self):
        with patch.dict(update.os.environ, {}, clear=True), \
                patch.object(update.os, "_exit", side_effect=SystemExit) as exit_call, \
                patch.object(update.os, "execv") as exec_call, \
                patch.object(update.subprocess, "Popen") as spawn:
            with self.assertRaises(SystemExit):
                update._restart_app()
            spawn.assert_called_once_with([sys.executable] + sys.argv, start_new_session=True)
            exit_call.assert_called_once_with(0)
            exec_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()

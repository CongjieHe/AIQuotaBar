"""Menu bar segments, reset timestamps, notifications and the instance lock."""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Importing aiquotabar.config migrates and writes files under $HOME: never let
# the tests touch the real one.
os.environ["HOME"] = tempfile.mkdtemp(prefix="aiquotabar-test-home-")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiquotabar.ui as ui  # noqa: E402  (rumps/AppKit load before curl_cffi)
from aiquotabar import providers  # noqa: E402
from aiquotabar.providers import LimitRow, ProviderData, UsageData  # noqa: E402

ui.log.disabled = True


def make_app(config: dict) -> ui.ClaudeBar:
    app = object.__new__(ui.ClaudeBar)
    app.config = config
    app._config_lock = threading.Lock()
    app._provider_data = []
    app._cc_stats = None
    app._last_data = None
    app._last_title_at = None
    return app


def seg(app, data):
    return [(s["name"], s.get("tag"), s["pct"], s["suffix"]) for s in app._bar_segments(data)]


SESSION = LimitRow("5H", 42, "resets in 2h", resets_at=time.time() + 7200)
WEEKLY = LimitRow("7D", 10, "resets Fri 02:00")
FABLE = LimitRow("7D Fable", 97, "resets Fri 02:00")
CLAUDE = UsageData(session=SESSION, weekly_all=WEEKLY, scoped=[FABLE])


class BarSegmentTests(unittest.TestCase):
    def test_default_is_claude_session_with_weekly_maxed_hint(self):
        app = make_app({})
        self.assertEqual(seg(app, CLAUDE), [("Claude", None, 42, " ·")])

    def test_chosen_claude_limits_get_tags_in_canonical_order(self):
        app = make_app({"claude_bar_limits": ["7D Fable", "5H"]})
        self.assertEqual(seg(app, CLAUDE), [("Claude", "5h", 42, ""),
                                            ("Claude", "7d·F", 97, "")])

    def test_missing_chosen_limit_falls_back_to_primary(self):
        app = make_app({"claude_bar_limits": ["7D Opus"]})
        self.assertEqual(seg(app, CLAUDE), [("Claude", None, 42, " ·")])

    def test_explicit_providers_keep_placeholder_slots(self):
        app = make_app({"bar_providers": ["Cursor", "Claude"]})
        app._provider_data = [ProviderData("Cursor", error="HTTP Error 401: ")]
        self.assertEqual(seg(app, CLAUDE), [("Cursor", None, None, ""),
                                            ("Claude", None, 42, " ·")])

    def test_provider_segment_uses_worst_row_and_its_reset(self):
        app = make_app({})
        cur = ProviderData("Cursor", spent=1.0, limit=100.0)
        cur._rows = [LimitRow("Auto", 5, "", 100.0), LimitRow("API", 60, "", 200.0)]
        app._provider_data = [cur]
        [_, cursor] = app._bar_segments(CLAUDE)
        self.assertEqual((cursor["pct"], cursor["resets_at"]), (60, 200.0))

    def test_severity_and_countdown_format(self):
        self.assertEqual([ui._severity(p) for p in (None, 79, 80, 94, 95)],
                         [None, None, "warn", "warn", "crit"])
        self.assertEqual([ui._fmt_countdown(s) for s in (5, 47 * 60, 3600, 4 * 3600 + 480)],
                         ["1m", "47m", "1h", "4h 8m"])

    def test_plain_title_shows_tags_and_only_imminent_countdowns(self):
        app = make_app({"claude_bar_limits": ["5H", "7D"], "bar_show_reset": True})
        week = LimitRow("7D", 10, "", resets_at=time.time() + 3 * 86400)
        app._set_bar_title(app._bar_segments(UsageData(session=SESSION, weekly_all=week)))
        # No status item in the test, so the attributed path falls back to text.
        self.assertRegex(app._title, r"^● 5h 42% 1h 59m  ● 7d 10%$")

    def test_claude_limit_picker_keeps_at_least_one(self):
        app = make_app({})
        app._apply = lambda data: None
        with patch.object(ui, "save_config"):
            app._make_claude_limit_cb("7D")(None)
            self.assertEqual(app.config["claude_bar_limits"], ["5H", "7D"])
            app._make_claude_limit_cb("5H")(None)
            app._make_claude_limit_cb("7D")(None)      # last one: ignored
            self.assertEqual(app.config["claude_bar_limits"], ["7D"])


class ProviderParsingTests(unittest.TestCase):
    def test_claude_rows_carry_reset_timestamps(self):
        data = providers.parse_usage({"usage": {
            "five_hour": {"utilization": 3, "resets_at": "2030-01-01T00:00:00+00:00"},
            "limits": [{"kind": "weekly_scoped", "percent": 7,
                        "resets_at": "2030-01-02T00:00:00Z",
                        "scope": {"model": {"display_name": "Fable"}}}],
        }})
        self.assertEqual(data.session.resets_at, 1893456000.0)
        self.assertEqual(data.scoped[0].resets_at, 1893542400.0)

    def test_org_uuid_beats_legacy_numeric_id(self):
        self.assertEqual(providers._org_uuid({"id": 123, "uuid": "u-1"}), "u-1")
        self.assertEqual(providers._org_uuid({"id": "only-id"}), "only-id")
        self.assertIsNone(providers._org_uuid(None))
        with patch.object(providers, "_get", return_value=[{"id": 9, "uuid": "u-9"}]):
            self.assertEqual(providers._org_id_from_api({}), "u-9")


class NotifyTests(unittest.TestCase):
    def test_falls_back_to_osascript_when_rumps_cannot_notify(self):
        with patch.object(ui.rumps, "notification", side_effect=RuntimeError("no plist")), \
                patch.object(ui.subprocess, "Popen") as popen:
            ui._notify('Say "hi"', "sub", "msg")
        args = popen.call_args[0][0]
        self.assertEqual(args[:2], ["osascript", "-e"])
        self.assertEqual(args[2], 'display notification "msg" '
                                  'with title "Say \\"hi\\"" subtitle "sub"')


class SingleInstanceTests(unittest.TestCase):
    def test_second_copy_waits_then_gives_up(self):
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import sys, time; sys.path.insert(0, sys.argv[1]);"
             "from aiquotabar.__main__ import _single_instance;"
             "print(_single_instance(), flush=True); time.sleep(2)", str(ROOT)],
            stdout=subprocess.PIPE, text=True, env=os.environ)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "True")
            from aiquotabar.__main__ import _single_instance
            start = time.monotonic()
            self.assertFalse(_single_instance(wait=0.5))
            self.assertGreaterEqual(time.monotonic() - start, 0.5)
            # Once the holder exits, the lock is free again.
            self.assertTrue(_single_instance(wait=5))
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()


if __name__ == "__main__":
    unittest.main()

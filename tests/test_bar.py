"""Menu bar segments, reset timestamps, notifications and the instance lock."""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        self.assertEqual([providers.fmt_left(s) for s in
                          (5, 47 * 60, 3600, 4 * 3600 + 480, 86400, 39 * 3600 + 900)],
                         ["1m", "47m", "1h", "4h 8m", "1d", "1d 15h"])

    def test_weekly_resets_show_time_left_and_local_weekday(self):
        ts = (time.time() // 60 + 39 * 60 + 5) * 60      # on a whole minute
        local = time.strftime("%a %H:%M", time.localtime(ts))
        week = LimitRow("7D", 11, providers._fmt_reset(ts), resets_at=ts)
        self.assertEqual(week.reset_str, "resets in 1d 15h")      # widget: short
        self.assertEqual(ui._reset_text(week), f"resets in 1d 15h \u00b7 {local}")
        soon = LimitRow("5H", 1, "", resets_at=(time.time() // 60 + 90) * 60)
        self.assertTrue(ui._reset_text(soon).startswith("resets in 1h"))   # no weekday
        self.assertEqual(ui._reset_text(LimitRow("5H", 0, "no active session")),
                         "no active session")

    def test_rows_resetting_together_share_one_line(self):
        minute = (time.time() // 60 + (2 * 24 + 5) * 60 + 30) * 60   # 2d 5h 30m out
        week = LimitRow("7D", 11, "", resets_at=minute + 0.44)          # API jitter
        fable = LimitRow("7D Fable", 17, "", resets_at=minute - 0.03)
        sonnet = LimitRow("7D Sonnet", 5, "", resets_at=minute + 3600)
        out = ui._shared_resets([week, fable, sonnet])
        self.assertEqual([r.label for r, _ in out], ["7D", "7D Fable", "7D Sonnet"])
        self.assertIsNone(out[0][1])
        local = time.strftime("%a %H:%M", time.localtime(minute))
        self.assertEqual(out[1][1], f"7D & 7D Fable: resets in 2d 5h \u00b7 {local}")
        self.assertTrue(out[2][1].startswith("resets in 2d 6h"))

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


class PanelTests(unittest.TestCase):
    """The floating panel, built offscreen; asserts on its text in reading order."""

    def render(self, data: UsageData) -> list[str]:
        from AppKit import NSView, NSTextField
        from Foundation import NSMakeRect

        class Sink:     # stands in for the window and scroll view
            def __getattr__(self, name):
                return lambda *a, **k: Sink()
        panel = object.__new__(ui._UsagePanel)
        panel._app = SimpleNamespace(_last_data=data, _provider_data=[], _history={},
                                     _history_db=None, _last_updated=None, _cc_stats=None)
        panel._handler = None
        panel._content_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 600))
        panel._panel = panel._scroll = Sink()
        panel._rebuild_content()

        def texts(view):
            own = [view.stringValue()] if isinstance(view, NSTextField) else []
            return [t for t in own if t] + [t for sv in view.subviews() for t in texts(sv)]
        return texts(panel._content_view)

    def test_each_reset_sits_under_its_rows(self):
        weekly = (time.time() // 60 + (2 * 24 + 5) * 60 + 30) * 60
        data = UsageData(
            session=LimitRow("5H", 15, "", resets_at=(time.time() // 60 + 200) * 60),
            weekly_all=LimitRow("7D", 12, "", resets_at=weekly),
            scoped=[LimitRow("7D Fable", 18, "", resets_at=weekly)])
        t = self.render(data)
        claude = t[t.index("Claude"):]
        # No reset beside the "Claude" title: the 5H reset follows its own row.
        self.assertEqual(claude[1:3], ["5H", "15%"])
        self.assertTrue(claude[3].startswith("\u21bb resets in 3h"), claude)
        self.assertEqual(claude[4:8], ["7D", "12%", "7D Fable", "18%"])
        self.assertTrue(claude[8].startswith("\u21bb 7D & 7D Fable: resets in 2d 5h"), claude)

    def test_idle_session_says_so_under_its_row(self):
        t = self.render(UsageData(session=LimitRow("5H", 0, "no active session")))
        self.assertEqual(t[t.index("5H"):][:3], ["5H", "0%", "\u21bb no active session"])


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


class OutageTests(unittest.TestCase):
    """Network errors keep the last good data and retry every 15 minutes; the
    error shows after 4 failed retries (1 hour). Auth errors show at once."""

    GOOD = ProviderData("Cursor", spent=1.0, limit=100.0)
    TIMEOUT = ProviderData("Cursor", error="curl: (28) Operation timed out after 10002 ms")
    UNREACHABLE = r"^Unreachable since \d\d:\d\d \(timed out\)$"

    def setUp(self):
        self.now = time.time()   # real "today", so messages use the HH:MM form
        clock = patch.object(ui.time, "time", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def provider_app(self, replies):
        app = make_app({"fake_key": "cookie"})
        app._outages, app._last_good, app._stale_providers = {}, {}, set()
        app._cookie_redetect_at = {}
        replies = iter(replies)
        self.calls = 0

        def fetch(_key):
            self.calls += 1
            return next(replies)
        for p in (patch.object(ui, "PROVIDER_REGISTRY", {"fake_key": ("Cursor", fetch)}),
                  patch.object(ui, "COOKIE_PROVIDERS", set())):
            p.start()
            self.addCleanup(p.stop)
        return app

    def test_network_error_keeps_data_and_retries_every_15_min(self):
        app = self.provider_app([self.GOOD] + [self.TIMEOUT] * 5)
        app._fetch_providers()
        t0 = self.now
        app._fetch_providers()                         # first failure: keep data
        self.assertIs(app._provider_data[0], self.GOOD)
        self.assertEqual(app._stale_providers, {"Cursor"})
        self.now = t0 + 5 * 60
        app._fetch_providers()                         # not due: no request
        self.assertEqual(self.calls, 2)
        for retry in (1, 2, 3):
            self.now = t0 + retry * ui.RETRY_INTERVAL
            app._fetch_providers()
            self.assertIs(app._provider_data[0], self.GOOD)
        self.now = t0 + 4 * ui.RETRY_INTERVAL
        app._fetch_providers()                         # 4th failed retry: 1h down
        self.assertEqual(self.calls, 6)
        self.assertRegex(app._provider_data[0].error, self.UNREACHABLE)
        self.assertEqual(app._stale_providers, set())

    def test_success_and_auth_error_end_the_outage(self):
        auth = ProviderData("Cursor", error="HTTP Error 401: ")
        app = self.provider_app([self.GOOD, self.TIMEOUT, self.GOOD, self.TIMEOUT, auth])
        app._fetch_providers()
        app._fetch_providers()
        self.now += ui.RETRY_INTERVAL
        app._fetch_providers()                         # recovered
        self.assertEqual(app._outages, {})
        app._fetch_providers()                         # a new outage...
        self.now += ui.RETRY_INTERVAL
        app._fetch_providers()                         # ...ended by a dead session
        self.assertEqual(app._provider_data[0].error, "HTTP Error 401: ")
        self.assertEqual(app._outages, {})

    def test_refresh_now_retries_without_using_up_a_retry(self):
        app = self.provider_app([self.GOOD, self.TIMEOUT, self.TIMEOUT])
        app._fetch_providers()
        app._fetch_providers()
        app._fetch_providers(force=True)
        self.assertEqual(self.calls, 3)
        self.assertEqual(app._outages["fake_key"]["retries"], 0)

    def test_without_earlier_data_the_error_shows_at_once(self):
        app = self.provider_app([self.TIMEOUT])
        app._fetch_providers()
        self.assertRegex(app._provider_data[0].error, self.UNREACHABLE)

    def test_claude_follows_the_same_policy(self):
        app = make_app({"cookie_str": "sessionKey=x"})
        app._outages, app._auth_fail_count, app._last_data = {}, 0, CLAUDE
        with patch.object(ui, "fetch_raw", side_effect=OSError("Connection timed out")):
            t0 = self.now
            self.assertIs(app._fetch_claude(), CLAUDE)
            for retry in (1, 2, 3):
                self.now = t0 + retry * ui.RETRY_INTERVAL
                self.assertIs(app._fetch_claude(), CLAUDE)
            self.now = t0 + 4 * ui.RETRY_INTERVAL
            data = app._fetch_claude()
        self.assertIsNone(data.session)
        self.assertRegex(data.error, self.UNREACHABLE)

    def test_error_texts(self):
        self.assertEqual(ui._short_reason(
            "Failed to perform, curl: (28) Connection timed out after 10003 milliseconds. "
            "See https://curl.se/libcurl/c/libcurl-errors.html"), "timed out")
        self.assertEqual(ui._short_reason("curl: (6) Could not resolve host: claude.ai"),
                         "DNS lookup failed")
        self.assertEqual(ui._short_reason("curl: (7) Failed to connect to claude.ai:443"),
                         "connection failed")
        self.assertEqual(ui._short_reason("HTTP Error 502: "), "HTTP 502")
        self.assertEqual(providers.display_error("Cursor", "HTTP Error 401: "),
                         "Session expired \u2014 sign in at cursor.com")


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

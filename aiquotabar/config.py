"""Configuration constants and persistence."""

import json
import os
import logging
import logging.handlers

# ── paths ────────────────────────────────────────────────────────────────────

APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/AIQuotaBar")
CONFIG_FILE = os.path.join(APP_SUPPORT_DIR, "config.json")
LOG_FILE = os.path.join(APP_SUPPORT_DIR, "aiquotabar.log")
HISTORY_FILE = os.path.join(APP_SUPPORT_DIR, "history.json")
LOG_BACKUPS = 3

LAUNCH_AGENT_LABEL = "com.aiquotabar"
LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{LAUNCH_AGENT_LABEL}.plist"
)
# Names used before the app was renamed from "Claude Usage Bar".
LEGACY_LAUNCH_AGENT_LABEL = "com.claudebar"
LEGACY_LAUNCH_AGENT_PLIST = os.path.expanduser(
    f"~/Library/LaunchAgents/{LEGACY_LAUNCH_AGENT_LABEL}.plist"
)


def _migrate_legacy_files():
    """Move pre-rename ~/.claude_bar* files into APP_SUPPORT_DIR (one-time).

    Runs before logging is configured, so it must not log. A destination that
    already has content wins; an empty one is the log file launchd creates
    for StandardOutPath before Python starts, and is safe to replace.
    """
    os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    pairs = [
        ("~/.claude_bar_config.json", CONFIG_FILE),
        ("~/.claude_bar_history.json", HISTORY_FILE),
    ] + [
        (f"~/.claude_bar.log{sfx}", f"{LOG_FILE}{sfx}")
        for sfx in [""] + [f".{i}" for i in range(1, LOG_BACKUPS + 1)]
    ]
    for old, new in pairs:
        old = os.path.expanduser(old)
        try:
            if not os.path.exists(old):
                continue
            if os.path.exists(new) and os.path.getsize(new) > 0:
                continue
            os.replace(old, new)
        except OSError:
            pass


_migrate_legacy_files()

# ── logging ──────────────────────────────────────────────────────────────────

_log_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=LOG_BACKUPS,
)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.basicConfig(handlers=[_log_handler], level=logging.DEBUG)
log = logging.getLogger("aiquotabar")

# ── thresholds ───────────────────────────────────────────────────────────────

REFRESH_INTERVALS = {
    "1 min":  60,
    "5 min":  300,
    "15 min": 900,
}
DEFAULT_REFRESH = 300

WARN_THRESHOLD = 80   # notify when any limit crosses this %
CRIT_THRESHOLD = 95   # title turns red emoji above this %

WIDGET_HOST_APP = "/Applications/AIQuotaBarHost.app"
WIDGET_CACHE_DIR = APP_SUPPORT_DIR
WIDGET_CACHE_FILE = os.path.join(WIDGET_CACHE_DIR, "usage.json")

# ── notification defaults ─────────────────────────────────────────────────────
# Keys stored in config under "notifications": { key: bool }
NOTIF_DEFAULTS = {
    "claude_reset":   True,   # notify when Claude session/weekly resets
    "chatgpt_reset":  True,   # notify when ChatGPT rate-limit resets
    "claude_warning": True,   # notify when Claude usage crosses WARN/CRIT
    "chatgpt_warning":True,   # notify when ChatGPT usage crosses WARN/CRIT
    "claude_pacing":  True,   # predictive alert when Claude ETA < 30 min
    "chatgpt_pacing": True,   # predictive alert when ChatGPT ETA < 30 min
    "copilot_pacing": True,   # predictive alert when Copilot ETA < 30 min
    "cursor_warning": True,   # notify when Cursor usage crosses WARN/CRIT
    "cursor_pacing":  True,   # predictive alert when Cursor ETA < 30 min
}

# ── usage history + burn rate ────────────────────────────────────────────────

HISTORY_MAX_AGE = 24 * 3600  # prune entries older than 24 h
PACING_ALERT_MINUTES = 30    # alert when ETA drops below this

# ── SQLite long-term history ─────────────────────────────────────────────────
HISTORY_DB = os.path.join(APP_SUPPORT_DIR, "history.db")
SAMPLES_MAX_DAYS = 7
DAILY_MAX_DAYS = 90
LIMIT_HIT_PCT = 95
BURN_WINDOW = 30 * 60       # regression window: 30 minutes
MIN_SPAN_SECS = 5 * 60      # need >=5 min of data before showing ETA
RESET_DROP_PCT = 30          # pct drop that signals a reset
UPDATE_CHECK_INTERVAL = 4 * 3600   # check for updates every 4 hours

HISTORY_COLORS = {
    "claude": "#D97757", "chatgpt": "#74AA9C",
    "copilot": "#6E40C9", "cursor": "#00A0D1",
}


# ── config persistence ───────────────────────────────────────────────────────

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            corrupt = CONFIG_FILE + ".bak"
            log.warning("Config file corrupt (%s), resetting. Backup at %s", e, corrupt)
            try:
                os.replace(CONFIG_FILE, corrupt)
            except OSError:
                pass
    return {}


def save_config(cfg: dict):
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_FILE)


def notif_enabled(cfg: dict, key: str) -> bool:
    """Return True if the named notification is enabled (defaults to True)."""
    return cfg.get("notifications", {}).get(key, NOTIF_DEFAULTS.get(key, True))


def set_notif(cfg: dict, key: str, value: bool):
    """Persist a single notification toggle."""
    cfg.setdefault("notifications", {})[key] = value
    save_config(cfg)


def provider_disabled(cfg: dict, cfg_key: str) -> bool:
    """True if the user has switched this provider off entirely.

    Disabled providers are never auto-detected, fetched, or displayed. This is
    distinct from "not configured" -- a disabled provider stays off even though
    its cookies are sitting in the browser waiting to be picked up.
    """
    return cfg_key in (cfg.get("disabled_providers") or [])


def set_provider_disabled(cfg: dict, cfg_key: str, disabled: bool):
    """Persist a single provider on/off toggle."""
    current = set(cfg.get("disabled_providers") or [])
    current.add(cfg_key) if disabled else current.discard(cfg_key)
    cfg["disabled_providers"] = sorted(current)
    save_config(cfg)

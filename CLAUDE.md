# CLAUDE.md — AIQuotaBar (personal fork)

## What this is

A personal fork of [yagcioglutoprak/AIQuotaBar](https://github.com/yagcioglutoprak/AIQuotaBar):
a native macOS menu bar app (Python + rumps) plus an optional WidgetKit widget that
show live AI usage limits. It reads session cookies from the browser, calls each
provider's usage API, and renders brand icon + percentage per provider in the menu bar.

- `origin` = `CongjieHe/AIQuotaBar` (this fork; the auto-updater pulls `origin/main`),
  `upstream` = the original repo. The fork has diverged (renamed files, removed
  Copilot and the share/star UI), so upstream changes need manual porting.
- Shown today: **Claude + Cursor**. ChatGPT is still supported in code but switched
  off via **Show Providers** (`disabled_providers`) — hide providers with that toggle,
  not by deleting display code. OpenAI / MiniMax / GLM are optional API-key providers.

## Architecture

Python package `aiquotabar/` with a thin `aiquotabar.py` entry point. No build step. No framework.

```
aiquotabar/
├── config.py     paths, load_config / save_config, legacy-file migration
├── providers.py  Claude API (fetch_raw/parse_usage), fetch_chatgpt / fetch_cursor /
│                 fetch_openai / fetch_minimax / fetch_glm → ProviderData
│                 PROVIDER_REGISTRY: cfg_key → (name, fetch_fn); COOKIE_PROVIDERS auto-detect
│                 Cookie mgmt: _auto_detect_*_cookies → browser-cookie3 (crash-safe subprocess)
├── ui.py         ClaudeBar(rumps.App) — timer, floating panel, menu, bar title, callbacks
├── history.py    usage history: history.json (24h, ETA/sparklines) + SQLite history.db
├── widget.py     _write_widget_cache → usage.json for the WidgetKit widget
└── update.py     silent git fast-forward + restart
```

Claude is not in `PROVIDER_REGISTRY`: it has its own fetch (`_fetch_claude`) and
always shows when it returns rows. It must never block the other providers — a
network error keeps the last snapshot, repeated 401/403 re-detects browser cookies
and retries once.

Note: Cursor's `usage-summary` API has two response shapes — individual plans return
`individualUsage.plan.*PercentUsed`; enterprise/team plans have no `plan` block and
`fetch_cursor` shows only the member's own quota from `individualUsage.overall`
(`used`/`limit` are in USD cents). Team-wide pools (`teamUsage`) are deliberately
not displayed — they are not the user's personal limit.

Note: ChatGPT's `wham/usage` returns `additional_rate_limits[]` — per-model side
buckets alongside the main `rate_limit`. `_WHAM_HIDDEN_LIMITS` in `providers.py`
filters these by `limit_name` substring; "spark" is hidden because Codex-Spark is a
speed-optimised preview model that is never the user's real ceiling. Filtering at
`_parse_wham_usage` covers the menu, the bar, the panel and the widget at once —
they all read `pd._rows`.

## Widget (optional)

A native macOS WidgetKit widget in `AIQuotaBarWidget/` shows usage on the desktop.
Build and install with `AIQuotaBarWidget/build_widget.sh` (needs Xcode).

**Data flow:** `aiquotabar.py` → `~/Library/Application Support/AIQuotaBar/usage.json` → WidgetKit reads it.

- `_write_widget_cache()` runs after every fetch cycle (atomic write, never crashes main app)
- It then runs `open -n -g -a AIQuotaBarHost --args --reload-widget` to nudge WidgetKit.
  The `-n` is required: plain `open` only activates an already-running host, so the
  `--reload-widget` arg would never reach it if any instance is lingering.
  `AIQuotaBarHostApp.init()` handles that flag by reloading timelines and calling
  `exit(0)` **before** the `WindowGroup` is built — otherwise every refresh cycle
  leaves a stray host window on the user's desktop.
- Widget refreshes every 5 min via `TimelineProvider` (matches the app's fetch cycle)
- Shows a "stale" badge (dimmed content + age) when the cache is >30 min old.
  `isStale` was computed but never rendered for a long time, which is how a
  9-day-old snapshot passed for live data — keep the badge wired to the views.
- The Swift side must track `usage.json` schema additions: `ClaudeUsage.scoped`
  mirrors `UsageData.scoped`. New keys are optional in Swift so an older cache
  still decodes; a *missing* non-optional key makes `JSONDecoder` return nil and
  the widget silently falls back to "no data".
- An untouched widget (intent still on a shipped default pair, see `isUsingDefaults`)
  follows the menu bar's provider choice via `bar_providers` in `usage.json`.
- Small widget: icon + percentage per provider. Medium: side-by-side bars.

## Adding a new provider

1. Write `fetch_myprovider(api_key: str) -> ProviderData` — return `ProviderData` with `spent`/`limit` or `balance`
2. Add one entry to `PROVIDER_REGISTRY`: `"myprovider_key": ("MyProvider", fetch_myprovider)`
3. That's it — the menu item, key dialog, and display are all automatic.

Users can switch any registry provider off via **Show Providers** in the menu. This
stores the cfg_key in `disabled_providers` (see `provider_disabled` in `config.py`);
a disabled provider is skipped by cookie auto-detect *and* by the fetch task list,
and is dropped from an explicit `bar_providers` choice, so it vanishes from the menu,
bar, panel and widget at once. This is stronger than "not configured" — without it,
auto-detect would silently re-add the provider on the next refresh.

## Key decisions to preserve

- **Session (5-hour) drives Claude's menu bar number**, not the max of all limits.
  Weekly limits appear in the menu/panel only. Session determines immediate access.
- **Firefox/LibreWolf first** in browser detection order — no Keychain prompt.
  Chromium browsers (Chrome, Arc, Brave, ...) come after; they need one-time "Always Allow".
- **API utilization is 0–100 everywhere** (`five_hour`, `seven_day`, `seven_day_sonnet`,
  `limits[].percent`). No conversion needed.
- **`rumps.notification` crashes** in dev (missing Info.plist CFBundleIdentifier).
  All notifications go through `_notify()` which swallows the exception silently.
- **Cookies are cached** in `config.json` (see Local files). Auto-detect runs when no
  cookie is saved and on repeated 401/403 failures to silently refresh the session.
- **Cookie providers self-heal.** ChatGPT/Cursor swallow HTTP errors into
  `ProviderData.error`, so `_fetch_providers` checks `is_auth_error()` and re-runs
  browser detection + one retry (15-min per-provider cooldown, `_redetect_cookies`).
- **Restarts always get a new PID.** On macOS 26+, re-exec'ing the AppKit process in
  place (`os.execv`) left Control Center holding the old process incarnation and
  rejecting every status-item scene — the app kept running with no menu bar icon.
  The updater exits 75 so launchd (`KeepAlive.SuccessfulExit=false`) respawns it, or
  spawns a new process for manual runs. It also only fast-forwards when HEAD is a
  strict ancestor of `origin/main`, and skips dirty trees.

## API behaviour (confirmed)

```
GET https://claude.ai/api/organizations/{org_id}/usage
```
Requires Cloudflare bypass — `curl_cffi` with `impersonate="safari184"` (Cloudflare
fingerprint-checks Chrome harder), and the Cloudflare cookies (`cf_clearance`,
`__cf_bm`, `_cfuvid`) stripped, since they are bound to the real browser's TLS stack.

Response fields:
| Field              | Meaning                        | Utilization scale |
|--------------------|--------------------------------|-------------------|
| `five_hour`        | Current session (5-hr limit)   | 0–100 percentage  |
| `seven_day`        | Weekly all-models              | 0–100 percentage  |
| `seven_day_sonnet` | Weekly Sonnet-only             | 0–100 percentage  |
| `extra_usage`      | Overage toggle (null = off)    | —                 |
| `limits[]`         | Generic per-limit array        | `percent` 0–100   |

Per-model weekly caps (Opus/Sonnet/Fable) are no longer in `seven_day_*` — those
come back null. They arrive as `limits[]` entries with `kind="weekly_scoped"` and
`scope.model.display_name`; `_scoped_rows` turns them into `UsageData.scoped`
(deduped by label against the legacy fields). `five_hour.resets_at` is null while
no 5-hour window is open — the session row then reads "no active session" instead
of a blank reset slot.

## Files

| File               | Purpose                                                       |
|--------------------|---------------------------------------------------------------|
| `aiquotabar.py`    | Entry point (imports `aiquotabar`)                            |
| `aiquotabar/`      | Application package (see Architecture)                        |
| `tests/`           | Updater regression tests (disposable git repos)               |
| `install.sh`       | One-line installer: clones this fork, venv, LaunchAgent, widget |
| `make_launcher.sh` | Creates /Applications/AIQuota.app — headless launcher that restarts the menu bar app + reloads the widget (Spotlight: "AIQuota") |
| `requirements.txt` | `rumps`, `curl_cffi`, `browser-cookie3`, `pyobjc-framework-Quartz` |
| `assets/`          | Provider icons used by the menu bar and menu                  |
| `AIQuotaBarWidget/`| Optional WidgetKit desktop widget (Xcode project)             |

### Local files

Everything the app writes lives in `~/Library/Application Support/AIQuotaBar/`:
`config.json` (settings + cached cookies), `aiquotabar.log` (+ `.1`–`.3`),
`history.json`, `history.db`, `usage.json` (widget cache). The LaunchAgent is
`com.aiquotabar`. Before the rename these were `~/.claude_bar_config.json`,
`~/.claude_bar.log`, `~/.claude_bar_history.json` and `com.claudebar`;
`_migrate_legacy_files()` moves the files on first import of `config.py`, and
`_add_login_item()` deletes (but does not unload) the old plist, so a legacy job
keeps running until logout instead of being duplicated.

macOS 27 puts Chrome's cookie DB behind "App Data" privacy protection
(`TCC denied kTCCServiceSystemPolicyAppDataDetailed for com.google.Chrome`).
Without Full Disk Access for the venv's real Python binary (`readlink -f .venv/bin/python3`),
every browser cookie detection silently returns nothing, so expired sessions never
self-heal. A python started from a terminal is attributed to the terminal, so test
cookie access through a one-off launchd job, not the shell.
On the same system `curl_cffi` only imports after CoreFoundation is loaded
(`ui.py` gets this via `rumps`); standalone scripts must `import CoreFoundation` first.

## Dev workflow

```bash
# Run locally
python3 aiquotabar.py

# Check logs
tail -f ~/Library/Application\ Support/AIQuotaBar/aiquotabar.log

# Tests (never against the real $HOME — see "Do not")
HOME=$(mktemp -d) .venv/bin/python -m unittest discover -s tests

# Quick syntax check
python3 -m py_compile aiquotabar.py aiquotabar/*.py

# Kill and restart
launchctl kickstart -k gui/$(id -u)/com.aiquotabar   # LaunchAgent install
pkill -f aiquotabar.py; sleep 1; python3 aiquotabar.py &   # manual run

# Rebuild + reinstall the widget
AIQuotaBarWidget/build_widget.sh
```

## Do not

- Do not write `@Parameter(default: .none)` in the widget's AppIntents code — the
  `default:` argument is Optional, so bare `.none` means Optional.none (no default),
  the intent fails to instantiate, and the widget is permanently stuck on its
  redacted placeholder. Always qualify: `default: AIProvider.none`.
- Do not leave xcodebuild output registered with LaunchServices — the build step
  auto-runs `lsregister -trusted` on the build-dir app, creating a duplicate widget
  registration that fights the /Applications copy (pluginUUID flapping in chronod).
  `build_widget.sh` does the `lsregister -u` + delete at the end — don't drop it.
- Do not restart the app with `os.execv` or anything else that keeps the PID (see
  "Restarts always get a new PID").
- Do not add a `session_key` field — the app uses full cookie strings, not just the session key.
- Do not multiply utilization values by 100 — all fields return 0–100 percentages directly.
- Do not call `rumps.notification()` directly — always use `_notify()`.
- Do not store cookies in plaintext anywhere other than `config.json` in the app data dir (outside the repo).
- Do not import `aiquotabar.config` in a script or test with the real `$HOME` unless you mean to:
  the import runs the legacy-file migration, and `set_provider_disabled` saves through
  `config.save_config` (patching `ui.save_config` does not stop it). Point `HOME` at a temp dir.
- Do not add Electron, a web server, or any always-on background process beyond the menu bar app itself.

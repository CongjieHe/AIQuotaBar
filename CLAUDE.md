# CLAUDE.md — AIQuotaBar

## Project goal

**Get maximum GitHub stars and widespread adoption.**
North star: **225 stars** (threshold to resubmit homebrew-core PR).
Every change must either (a) convert more visitors to stars, (b) bring new visitors, or (c) make the app so good people share it organically.

### Current stats (2026-03-01)
- 6 stars, 0 forks
- Early stage — need to build real traction from scratch

### Growth priorities (in order)
1. **Fix star conversion** — README must convince in 5 seconds (hook → GIF → install)
2. **Social proof loop** — HN/PH badges, testimonials, star count badge visible
3. **Distribution** — awesome-lists, Reddit, dev.to, Twitter/X, YouTube demos
4. **Shareability features** — screenshot/share menu item, referral nudges in-app
5. **Cross-platform** — Linux tray port opens 70% more developers
6. **SEO** — GitHub Pages landing page, proper meta tags, backlinks

### Channel status
| Channel | Status | Next action |
|---------|--------|-------------|
| HN | Show HN posted | Repost if no traction |
| Product Hunt | Not submitted | Submit on a Tuesday 12:01 AM PST |
| awesome-mac PR #1833 | Open | Follow up if stale >7d |
| open-source-mac-os-apps PR #1041 | Open | Follow up if stale >7d |
| awesome-claude PR #60 | Open | Follow up if stale >7d |
| awesome-claude-code #888 | Auto-closed | Resubmit after 2026-03-05 |
| Reddit r/ClaudeAI | Rejected once | Repost with value-first copy |
| Reddit r/ChatGPT, r/macapps, r/commandline | Not posted | Post with screenshots |
| AlternativeTo | Listed | Done |
| dev.to | Published | Done |
| Twitter/X | Not posted | Post demo GIF + install command |
| GitHub Pages | Live | Improve SEO meta tags |
| Homebrew core | Needs 225 stars | Blocked on stars |
| Indie Hackers | Blocked (new account) | Build karma via comments |

## What this is

A native macOS menu bar app (Python + rumps) that shows live Claude, ChatGPT, Cursor, and GitHub Copilot usage limits. It reads cookies from the user's browser (no manual copy-paste), calls provider APIs, and displays the result as a status bar icon (`🟢 4%`, `🟡 83%`, `🔴 100%`).

## Architecture

Python package `aiquotabar/` with a thin `aiquotabar.py` entry point. No build step. No framework.

```
aiquotabar/
├── config.py     paths, load_config / save_config, legacy-file migration
├── providers.py  Claude API (fetch_raw), fetch_chatgpt / fetch_cursor / fetch_copilot /
│                 fetch_openai / fetch_minimax / fetch_glm → ProviderData
│                 PROVIDER_REGISTRY: cfg_key → (name, fetch_fn); COOKIE_PROVIDERS auto-detect
│                 Cookie mgmt: _auto_detect_*_cookies → browser-cookie3 (crash-safe subprocess)
├── ui.py         ClaudeBar(rumps.App) — timer, menu rebuild, bar title, callbacks
├── history.py    SQLite usage history (~/Library/Application Support/AIQuotaBar/history.db)
├── widget.py     _write_widget_cache → usage.json for the WidgetKit widget
└── update.py     update check
```

Note: Cursor's `usage-summary` API has two response shapes — individual plans return
`individualUsage.plan.*PercentUsed`; enterprise/team plans have no `plan` block and
`fetch_cursor` shows only the member's own quota from `individualUsage.overall`
(`used`/`limit` are in USD cents). Team-wide pools (`teamUsage`) are deliberately
not displayed — they are not the user's personal limit.

Note: ChatGPT's `wham/usage` returns `additional_rate_limits[]` — per-model side
buckets alongside the main `rate_limit`. `_WHAM_HIDDEN_LIMITS` in `providers.py`
filters these by `limit_name` substring; "spark" is hidden because Codex-Spark is a
speed-optimised preview model that is never the user's real ceiling. Filtering at
`_parse_wham_usage` covers the menu, the bar, the share card and the widget at once —
they all read `pd._rows`.

## Widget (optional)

A native macOS WidgetKit widget in `AIQuotaBarWidget/` shows usage on the desktop.

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
- Small widget: circular gauge (Claude session %). Medium: side-by-side bars
- Requires Xcode 15+ to build; entirely optional — menu bar app works without it

## Adding a new provider

1. Write `fetch_myprovider(api_key: str) -> ProviderData` — return `ProviderData` with `spent`/`limit` or `balance`
2. Add one entry to `PROVIDER_REGISTRY`: `"myprovider_key": ("MyProvider", fetch_myprovider)`
3. That's it — the menu item, key dialog, and display are all automatic.

Users can switch any registry provider off via **Show Providers** in the menu. This
stores the cfg_key in `disabled_providers` (see `provider_disabled` in `config.py`);
a disabled provider is skipped by cookie auto-detect *and* by the fetch task list, so
it vanishes from the menu, bar, share card and widget at once. Note this is stronger
than "not configured" — without it, auto-detect would silently re-add the provider on
the next refresh.

## Key decisions to preserve

- **Session (5-hour) drives the status bar icon**, not the max of all limits.
  Weekly limits appear in the menu only. Rationale: session determines immediate access.
- **Firefox/LibreWolf first** in browser detection order — no Keychain prompt, zero friction.
  Chromium browsers (Arc, Chrome, Brave) come after; they need one-time "Always Allow".
- **API utilization scale is now consistent**: all fields (`five_hour`, `seven_day`,
  `seven_day_sonnet`) return 0–100 percentage. No conversion needed.
- **`rumps.notification` crashes** in dev (missing Info.plist CFBundleIdentifier).
  All notifications go through `_notify()` which swallows the exception silently.
- **Cookies are cached** in `config.json` (see Local files). Auto-detect runs on first launch
  and on repeated 401/403 failures to silently refresh the session.
- **Cookie providers self-heal.** ChatGPT/Cursor/Copilot swallow HTTP errors into
  `ProviderData.error`, so `_fetch_providers` checks `is_auth_error()` and re-runs
  browser detection + one retry (15-min per-provider cooldown, `_redetect_cookies`).
  Without this a stale cached session made the provider silently vanish from the bar
  forever, since first-launch detection only fires when no key is saved at all.

## API behaviour (confirmed)

```
GET https://claude.ai/api/organizations/{org_id}/usage
```
Requires Cloudflare bypass — use `curl_cffi` with `impersonate="chrome131"`.

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

| File            | Purpose                                              |
|-----------------|------------------------------------------------------|
| `aiquotabar.py` | Entry point (imports `aiquotabar`)                   |
| `aiquotabar/`   | Application package (see Architecture)               |
| `install.sh`    | One-line curl installer (detects Python, LaunchAgent)|
| `make_launcher.sh` | Creates /Applications/AIQuota.app — headless launcher that restarts the menu bar app + reloads the widget (Spotlight: "AIQuota") |
| `requirements.txt` | `rumps`, `curl_cffi`, `browser-cookie3`           |
| `setup.sh`      | Legacy manual installer (kept for reference)         |
| `assets/`       | demo.gif and screenshots for README                  |
| `AIQuotaBarWidget/` | Optional WidgetKit desktop widget (Xcode project)   |

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
Without Full Disk Access for the venv's real Python binary, every browser
cookie detection silently returns nothing, so expired sessions never self-heal.
On the same system `curl_cffi` only imports after CoreFoundation is loaded
(`ui.py` gets this via `rumps`); standalone scripts must `import CoreFoundation` first.

## Growth / virality rules

- **README is a landing page, not docs.** Hook → GIF → install command must be above the fold.
  A visitor should understand value and install in under 10 seconds.
- **The demo GIF is the #1 driver of stars.** `assets/demo.gif` must be short, polished, and show
  the "aha moment": menu bar icon → click → full usage breakdown with colors.
- **Zero-friction install is non-negotiable.**
  `curl -fsSL .../install.sh | bash` must work end-to-end without manual steps.
  If it breaks, fix it before anything else.
- **Social proof converts.** Star count badge, download count, real testimonials — keep them visible.
  Never fake stats. Only show real numbers.
- **Every touchpoint should nudge stars.** Post-install terminal message, in-app menu item,
  GitHub Pages landing page — all link back to the repo.
- **Keep the README concise.** One install command, one GIF, short feature list.
  Long docs belong in a wiki, not the README.
- **GitHub topics to maintain** (set via repo Settings → About):
  `claude`, `anthropic`, `macos`, `menu-bar`, `usage-monitor`, `menubar-app`, `claude-ai`,
  `chatgpt`, `cursor`, `copilot`, `rate-limit`, `ai-tools`

## High-impact features to build (star drivers)

These features would make the app significantly more shareable:

1. **Gemini support** — Google's API has usage limits too; huge user base
2. **Linux system tray** — opens the app to 70% more developers (use pystray)
3. **Usage history chart** — "see your AI usage over time" is a compelling screenshot
4. **Share/export** — one-click screenshot of usage to clipboard (instant Twitter content)
5. **Claude Code / CLI tracking** — devs using Claude Code want to see limits too
6. **Notification Center widget** — already have WidgetKit, expose in NC for more visibility

## Dev workflow

```bash
# Run locally
python3 aiquotabar.py

# Check logs
tail -f ~/Library/Application\ Support/AIQuotaBar/aiquotabar.log

# Quick syntax check
python3 -m py_compile aiquotabar.py

# Kill and restart
launchctl kickstart -k gui/$(id -u)/com.aiquotabar   # LaunchAgent install
pkill -f aiquotabar.py; sleep 1; python3 aiquotabar.py &   # manual run
```

## Do not

- Do not write `@Parameter(default: .none)` in the widget's AppIntents code — the
  `default:` argument is Optional, so bare `.none` means Optional.none (no default),
  the intent fails to instantiate, and the widget is permanently stuck on its
  redacted placeholder. Always qualify: `default: AIProvider.none`.
- Do not leave xcodebuild output registered with LaunchServices — the build step
  auto-runs `lsregister -trusted` on the build-dir app, creating a duplicate widget
  registration that fights the /Applications copy (pluginUUID flapping in chronod).
  `build_widget.sh` now does the `lsregister -u` + delete at the end — don't drop it.

- Do not add a `session_key` field — the app uses full cookie strings, not just the session key.
- Do not multiply utilization values by 100 — all fields now return 0–100 percentages directly.
- Do not call `rumps.notification()` directly — always use `_notify()`.
- Do not store cookies in plaintext anywhere other than `config.json` in the app data dir (outside the repo).
- Do not import `aiquotabar.config` in a script or test with the real `$HOME` unless you mean to:
  the import runs the legacy-file migration, and `set_provider_disabled` saves through
  `config.save_config` (patching `ui.save_config` does not stop it). Point `HOME` at a temp dir.
- Do not add Electron, a web server, or any always-on background process beyond the menu bar app itself.
- Do not make the README longer than it already is — trim if anything.
- Do not add features that don't drive stars or retention. Every line of code should serve growth.

# AIQuotaBar

Personal fork of [yagcioglutoprak/AIQuotaBar](https://github.com/yagcioglutoprak/AIQuotaBar):
live Claude and Cursor usage limits in the macOS menu bar and a desktop widget.
Sessions are read from the browser — no API keys or cookie copy-pasting.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/CongjieHe/AIQuotaBar/main/install.sh | bash
```

This clones the repo to `~/.ai-quota-bar`, creates a venv, registers the
`com.aiquotabar` LaunchAgent (starts at login), builds the widget if Xcode is
installed, and creates `/Applications/AIQuota.app` (Spotlight "AIQuota" restarts
everything).

**macOS 27+:** Chrome's cookie store is privacy-protected. Give Full Disk Access to
the venv's real Python (`readlink -f ~/.ai-quota-bar/.venv/bin/python3`) in
System Settings → Privacy & Security, otherwise sessions are never detected or renewed.

Manual run:

```bash
git clone https://github.com/CongjieHe/AIQuotaBar.git && cd AIQuotaBar
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python3 aiquotabar.py
```

## What it shows

- **Menu bar:** brand icon + percentage per provider, orange from 80% and red from
  95%. Claude shows the 5-hour session by default; a trailing `·` means a weekly cap
  is maxed. A `–` means the provider has no data (not logged in, or the fetch failed).
  Under **Status Bar** you can add more Claude limits (e.g. `5h 3%  7d·F 0%`) and
  turn on a reset countdown for limits that reset within 24 hours.
- **Panel / menu** (click / right-click the icon): Claude 5-hour, weekly and
  per-model weekly limits, Cursor plan usage, reset times, burn-rate ETA and
  24h sparklines, plus local Claude Code activity.
- **Notifications** at 80% / 95%, on resets, and when the current pace hits a limit
  within 30 minutes.

Providers: Claude, Cursor and ChatGPT (cookie-based, auto-detected), plus OpenAI,
MiniMax and GLM (API key). Turn providers on/off under **Show Providers**; choose
which appear in the menu bar under **Status Bar**.

## Desktop widget

```bash
AIQuotaBarWidget/build_widget.sh   # needs Xcode; installs /Applications/AIQuotaBarHost.app
```

Then right-click the desktop → Edit Widgets → search "AI Quota". The widget reads
`usage.json` written by the menu bar app and follows its provider choice unless you
pick providers in the widget's own settings.

## Files

Everything lives in `~/Library/Application Support/AIQuotaBar/`: `config.json`
(settings and cached session cookies), `aiquotabar.log`, `history.json`,
`history.db`, `usage.json`.

## Troubleshooting

- **No menu bar icon:** `tail -50 ~/Library/Application\ Support/AIQuotaBar/aiquotabar.log`,
  then `launchctl kickstart -k gui/$(id -u)/com.aiquotabar`.
- **A provider shows `–`:** log in to that site in your browser; the app re-reads
  cookies automatically (on macOS 27+ only with Full Disk Access, see above). For
  Claude you can also use **Set Session Cookie…** / **Paste Cookie from Clipboard**.

## License

MIT — see [LICENSE](LICENSE). Not affiliated with Anthropic, OpenAI or Anysphere;
uses undocumented internal APIs that may change without notice.

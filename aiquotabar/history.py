"""Usage history tracking -- burn rate, sparklines, SQLite persistence."""

import json
import math
import os
import sqlite3
from datetime import datetime, timezone, timedelta

from aiquotabar.config import (
    log, HISTORY_FILE, HISTORY_MAX_AGE, HISTORY_DB,
    SAMPLES_MAX_DAYS, DAILY_MAX_DAYS, LIMIT_HIT_PCT,
    BURN_WINDOW, MIN_SPAN_SECS, RESET_DROP_PCT, HISTORY_COLORS,
)


def _nscolor(hex_str: str, alpha: float = 1.0):
    """Convert a hex color string like '#D97757' to an NSColor."""
    from AppKit import NSColor
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, alpha)


def _load_history() -> dict:
    """Load usage history from disk. Returns {"claude": [...], ...}."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_history(history: dict):
    """Persist usage history (atomic write)."""
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(history, f)
    os.replace(tmp, HISTORY_FILE)


def _append_history(history: dict, key: str, pct: int):
    """Append a timestamped pct snapshot, detect resets, and prune."""
    now = datetime.now(timezone.utc).timestamp()
    entries = history.setdefault(key, [])

    # Detect reset: if pct dropped by >=RESET_DROP_PCT, discard old data.
    # This prevents stale pre-reset points from poisoning the regression.
    if entries and (entries[-1]["pct"] - pct) >= RESET_DROP_PCT:
        entries.clear()

    entries.append({"t": now, "pct": pct})
    cutoff = now - HISTORY_MAX_AGE
    history[key] = [e for e in entries if e["t"] >= cutoff]


def _calc_burn_rate(history: dict, key: str) -> float | None:
    """Recency-weighted linear regression over the last 30 min.

    Uses exponential decay weighting (half-life = 10 min) so recent
    data points dominate and old bursts fade quickly.
    Timestamps are centered around their mean for numerical stability.

    Returns pct per minute (positive = increasing usage), or None if
    insufficient data or time span < 5 minutes.
    """
    entries = history.get(key, [])
    if len(entries) < 2:
        return None
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - BURN_WINDOW
    recent = [e for e in entries if e["t"] >= cutoff]
    if len(recent) < 2:
        return None

    # Require minimum time span to avoid noisy estimates from clustered points
    span = recent[-1]["t"] - recent[0]["t"]
    if span < MIN_SPAN_SECS:
        return None

    # Center timestamps for numerical stability
    t_mean = sum(e["t"] for e in recent) / len(recent)

    # Exponential decay weights: half-life of 10 minutes
    half_life = 10 * 60  # seconds
    decay = math.log(2) / half_life

    # Weighted linear regression
    sw = 0.0    # sum of weights
    swt = 0.0   # sum of w * t_centered
    swp = 0.0   # sum of w * pct
    swtp = 0.0  # sum of w * t_centered * pct
    swt2 = 0.0  # sum of w * t_centered^2

    for e in recent:
        tc = e["t"] - t_mean
        w = math.exp(-decay * (now - e["t"]))
        sw += w
        swt += w * tc
        swp += w * e["pct"]
        swtp += w * tc * e["pct"]
        swt2 += w * tc * tc

    denom = sw * swt2 - swt * swt
    if abs(denom) < 1e-10:
        return None
    slope = (sw * swtp - swt * swp) / denom  # pct per second
    return slope * 60  # pct per minute


def _calc_eta_minutes(history: dict, key: str) -> int | None:
    """Estimate minutes until 100% based on burn rate.

    Returns None if burn rate is non-positive or ETA > 10 hours.
    """
    entries = history.get(key, [])
    if not entries:
        return None
    current_pct = entries[-1]["pct"]
    rate = _calc_burn_rate(history, key)
    if rate is None or rate <= 0:
        return None
    remaining = 100 - current_pct
    if remaining <= 0:
        return 0
    eta = remaining / rate  # minutes
    if eta > 600:  # > 10 hours
        return None
    return max(1, round(eta))


def _fmt_eta(minutes: int) -> str:
    """Format ETA: 47 -> '47 min', 90 -> '1h 30 min', 360 -> '6h 0 min'."""
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h}h {m} min"


def _sparkline(history: dict, key: str, width: int = 20) -> str:
    """Render a sparkline from history using block chars.

    Returns empty string if fewer than 3 points or no meaningful variation.
    """
    entries = history.get(key, [])
    if len(entries) < 3:
        return ""
    blocks = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    pts = [e["pct"] for e in entries[-width:]]
    lo, hi = min(pts), max(pts)
    # Skip if all values are the same (no variation -> flat line looks bad)
    if hi - lo < 2:
        return ""
    span = hi - lo
    return "".join(blocks[min(7, int((p - lo) / span * 7))] for p in pts)


# -- SQLite history functions --------------------------------------------------

def _init_history_db() -> sqlite3.Connection:
    """Create/open the SQLite history database. Returns a WAL-mode connection."""
    os.makedirs(os.path.dirname(HISTORY_DB), exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS samples (
            ts   REAL NOT NULL,
            key  TEXT NOT NULL,
            pct  INTEGER NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_samples_key_ts ON samples(key, ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            date       TEXT NOT NULL,
            key        TEXT NOT NULL,
            peak_pct   INTEGER NOT NULL,
            avg_pct    INTEGER NOT NULL,
            limit_hits INTEGER NOT NULL DEFAULT 0,
            samples    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (date, key)
        )
    """)
    conn.commit()
    return conn


def _record_sample(conn: sqlite3.Connection, key: str, pct: int):
    """Insert one usage sample into the samples table (caller should batch commits)."""
    now = datetime.now(timezone.utc).timestamp()
    conn.execute("INSERT INTO samples (ts, key, pct) VALUES (?, ?, ?)", (now, key, pct))


def _rollup_daily_stats(conn: sqlite3.Connection):
    """Aggregate completed days from samples into daily_stats, then prune old data."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Find all distinct dates in samples that are before today
    rows = conn.execute(
        "SELECT DISTINCT date(ts, 'unixepoch') AS d FROM samples WHERE d < ? ORDER BY d",
        (today,),
    ).fetchall()

    for (day,) in rows:
        # Aggregate that day's samples per key
        agg = conn.execute("""
            SELECT key, MAX(pct), CAST(AVG(pct) AS INTEGER), COUNT(*),
                   SUM(CASE WHEN pct >= ? THEN 1 ELSE 0 END)
            FROM samples
            WHERE date(ts, 'unixepoch') = ?
            GROUP BY key
        """, (LIMIT_HIT_PCT, day)).fetchall()

        for key, peak, avg, cnt, hits in agg:
            conn.execute("""
                INSERT INTO daily_stats (date, key, peak_pct, avg_pct, limit_hits, samples)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, key) DO UPDATE SET
                    peak_pct=excluded.peak_pct, avg_pct=excluded.avg_pct,
                    limit_hits=excluded.limit_hits, samples=excluded.samples
            """, (day, key, peak, avg, hits, cnt))

        # Delete rolled-up samples
        conn.execute("DELETE FROM samples WHERE date(ts, 'unixepoch') = ?", (day,))

    # Prune old data
    cutoff_samples = (datetime.now(timezone.utc) - timedelta(days=SAMPLES_MAX_DAYS)).timestamp()
    conn.execute("DELETE FROM samples WHERE ts < ?", (cutoff_samples,))
    cutoff_daily = (datetime.now(timezone.utc) - timedelta(days=DAILY_MAX_DAYS)).strftime("%Y-%m-%d")
    conn.execute("DELETE FROM daily_stats WHERE date < ?", (cutoff_daily,))
    conn.commit()


def _get_weekly_stats(conn: sqlite3.Connection, key: str) -> list[dict]:
    """Return last 7 days of daily_stats for a given key, ordered by date."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT date, peak_pct, avg_pct, limit_hits, samples FROM daily_stats "
        "WHERE key = ? AND date >= ? ORDER BY date",
        (key, cutoff),
    ).fetchall()
    return [
        {"date": r[0], "peak_pct": r[1], "avg_pct": r[2], "limit_hits": r[3], "samples": r[4]}
        for r in rows
    ]


def _get_week_limit_hits(conn: sqlite3.Connection, key: str) -> int:
    """Return total number of limit-hit samples in the past 7 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COALESCE(SUM(limit_hits), 0) FROM daily_stats WHERE key = ? AND date >= ?",
        (key, cutoff),
    ).fetchone()
    # Also count today's samples that are at limit
    cutoff_ts = (datetime.now(timezone.utc) - timedelta(days=7)).timestamp()
    today_row = conn.execute(
        "SELECT COUNT(*) FROM samples WHERE key = ? AND pct >= ? AND ts >= ?",
        (key, LIMIT_HIT_PCT, cutoff_ts),
    ).fetchone()
    return (row[0] if row else 0) + (today_row[0] if today_row else 0)


def _get_today_stats(conn: sqlite3.Connection) -> dict[str, dict]:
    """Compute live stats from today's samples (not yet rolled up)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT key, MAX(pct), CAST(AVG(pct) AS INTEGER), COUNT(*),
               SUM(CASE WHEN pct >= ? THEN 1 ELSE 0 END)
        FROM samples
        WHERE date(ts, 'unixepoch') = ?
        GROUP BY key
    """, (LIMIT_HIT_PCT, today)).fetchall()
    result = {}
    for key, peak, avg, cnt, hits in rows:
        result[key] = {
            "date": today, "peak_pct": peak, "avg_pct": avg,
            "limit_hits": hits, "samples": cnt,
        }
    return result


def _fetch_history_data(conn: sqlite3.Connection) -> dict | None:
    """Gather all history data for the Usage History window."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cutoff_90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # All daily_stats rows within 90 days
    past_rows = conn.execute(
        "SELECT date, key, peak_pct, avg_pct, limit_hits, samples "
        "FROM daily_stats WHERE date >= ? ORDER BY date",
        (cutoff_90,),
    ).fetchall()

    # Today's live data
    today_stats = _get_today_stats(conn)

    # Merge into per-key and per-day structures
    per_key: dict[str, list[dict]] = {}
    per_day: dict[str, int] = {}  # date -> max avg across all providers (daily metric)
    per_day_detail: dict[str, dict] = {}  # date -> {key: {peak_pct, avg_pct}}

    for date, key, peak, avg, hits, cnt in past_rows:
        per_key.setdefault(key, []).append({
            "date": date, "peak_pct": peak, "avg_pct": avg,
            "limit_hits": hits, "samples": cnt,
        })
        per_day[date] = max(per_day.get(date, 0), avg)
        per_day_detail.setdefault(date, {})[key] = {"peak_pct": peak, "avg_pct": avg}

    for key, stat in today_stats.items():
        per_key.setdefault(key, []).append(stat)
        per_day[today] = max(per_day.get(today, 0), stat["avg_pct"])
        per_day_detail.setdefault(today, {})[key] = {
            "peak_pct": stat["peak_pct"], "avg_pct": stat["avg_pct"],
        }

    # Intraday 5-hour windows for today (from raw samples)
    today_windows: dict[str, dict[int, int]] = {}
    try:
        raw = conn.execute(
            "SELECT key, ts, pct FROM samples WHERE date(ts, 'unixepoch') = ? ORDER BY ts",
            (today,),
        ).fetchall()
        for key, ts, pct in raw:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            widx = min(dt.hour // 5, 4)
            bucket = today_windows.setdefault(key, {})
            bucket[widx] = max(bucket.get(widx, 0), pct)
    except Exception:
        log.debug("Failed to fetch intraday windows", exc_info=True)

    if not per_day:
        return None

    # Build provider summaries
    _day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    providers = []
    for key in sorted(per_key):
        stats = per_key[key]
        peaks = [d["peak_pct"] for d in stats]
        avgs = [d["avg_pct"] for d in stats]
        avg_val = round(sum(avgs) / len(avgs)) if avgs else 0
        peak_val = max(peaks) if peaks else 0
        total_hits = sum(d["limit_hits"] for d in stats)
        # Color: use parent provider color for sub-keys
        color = HISTORY_COLORS.get(key)
        if color is None:
            for prefix in ("chatgpt", "cursor", "claude"):
                if key.startswith(prefix):
                    color = HISTORY_COLORS[prefix]
                    break
            else:
                color = "#AAAAAA"
        label = (key.replace("_", " ").title()
                 .replace("Chatgpt", "ChatGPT").replace("Api", "API"))

        # Last 7 days for bar chart
        cutoff_7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly = [d for d in stats if d["date"] >= cutoff_7]

        providers.append({
            "key": key, "label": label, "color": color,
            "weekly": weekly, "avg": avg_val, "peak": peak_val, "hits": total_hits,
        })

    # Summary
    all_peaks = list(per_day.items())
    highest = max(all_peaks, key=lambda x: x[1])
    lowest = min(all_peaks, key=lambda x: x[1])
    avg_overall = round(sum(v for _, v in all_peaks) / len(all_peaks)) if all_peaks else 0
    total_hits = sum(p["hits"] for p in providers)
    earliest = min(per_day.keys())

    def _fmt_day(date_str):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            return f"{_day_names[dt.weekday()]} {dt.strftime('%b %d')}"
        except Exception:
            return date_str

    return {
        "days": per_day,
        "providers": providers,
        "per_day_detail": per_day_detail,
        "today_windows": today_windows,
        "summary": {
            "total_days": len(per_day),
            "earliest": earliest,
            "highest": (_fmt_day(highest[0]), highest[1]),
            "lowest": (_fmt_day(lowest[0]), lowest[1]),
            "avg": avg_overall,
            "total_hits": total_hits,
        },
    }


def cli_history():
    """Print a 7-day usage history chart to the terminal."""
    if not os.path.exists(HISTORY_DB):
        print("No history data yet. Run AIQuotaBar for a while first.")
        return

    conn = sqlite3.connect(HISTORY_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    keys = [r[0] for r in conn.execute(
        "SELECT DISTINCT key FROM daily_stats ORDER BY key"
    ).fetchall()]

    if not keys:
        print("No history data yet. Run AIQuotaBar for a while first.")
        conn.close()
        return

    # ANSI color map per provider prefix
    _colors = {
        "claude": "\033[38;5;209m",   # orange
        "chatgpt": "\033[38;5;114m",  # green
        "cursor": "\033[38;5;45m",    # cyan
    }
    _reset = "\033[0m"
    _dim = "\033[2m"
    _bold = "\033[1m"

    print(f"\n{_bold}  AIQuotaBar -- 7-Day Usage History{_reset}\n")

    for key in keys:
        stats = _get_weekly_stats(conn, key)
        if not stats:
            continue

        # Determine color from key prefix
        prefix = key.split("_")[0]
        color = _colors.get(prefix, "")
        label = key.replace("_", " ").title()

        print(f"  {color}{_bold}{label}{_reset}")

        bar_width = 30
        for d in stats:
            try:
                day_name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a")
            except Exception:
                day_name = d["date"][-5:]
            pct = d["peak_pct"]
            filled = round(pct / 100 * bar_width)
            bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
            hit_mark = " \u26a0" if d["limit_hits"] > 0 else ""
            print(f"    {_dim}{day_name}{_reset}  {color}{bar}{_reset}  {pct}%{hit_mark}")

        # Summary line
        peaks = [d["peak_pct"] for d in stats]
        avgs = [d["avg_pct"] for d in stats]
        total_hits = sum(d["limit_hits"] for d in stats)
        avg_all = round(sum(avgs) / len(avgs)) if avgs else 0
        peak_all = max(peaks) if peaks else 0
        summary = f"    avg {avg_all}%  \u00b7  peak {peak_all}%"
        if total_hits > 0:
            summary += f"  \u00b7  hit limit {total_hits}x"
        print(f"  {_dim}{summary}{_reset}\n")

    conn.close()

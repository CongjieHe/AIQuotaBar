"""Silent auto-update via git pull."""

import os
import subprocess
import sys

from aiquotabar.config import (
    log, LAUNCH_AGENT_LABEL, LEGACY_LAUNCH_AGENT_LABEL,
)


def _check_and_apply_update() -> bool:
    """Silently check for updates via git and apply if available. Returns True if updated."""
    install_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isdir(os.path.join(install_dir, ".git")):
        return False  # Not a git install (Homebrew, dev, etc.)
    try:
        run = lambda cmd: subprocess.run(
            cmd, cwd=install_dir, capture_output=True, text=True, timeout=30
        )
        r = run(["git", "fetch", "--quiet", "origin"])
        if r.returncode != 0:
            return False
        local_ref = run(["git", "rev-parse", "HEAD"])
        remote_ref = run(["git", "rev-parse", "origin/main"])
        if local_ref.returncode or remote_ref.returncode:
            return False
        local, remote = local_ref.stdout.strip(), remote_ref.stdout.strip()
        if local == remote:
            return False  # Already up to date
        # Different hashes do not imply an update: local commits may be ahead
        # of upstream. Merging an ancestor succeeds without changing HEAD.
        if run(["git", "merge-base", "--is-ancestor", local, remote]).returncode != 0:
            log.debug("auto-update skipped: local history is ahead or diverged")
            return False
        status = run(["git", "status", "--porcelain"])
        if status.returncode or status.stdout.strip():
            log.debug("auto-update skipped: working tree has local changes")
            return False
        r = run(["git", "merge", "--ff-only", remote, "--quiet"])
        if r.returncode != 0:
            log.warning("auto-update merge failed: %s", r.stderr)
            return False
        updated = run(["git", "rev-parse", "HEAD"])
        if updated.returncode or updated.stdout.strip() != remote:
            return False
        venv_pip = os.path.join(install_dir, ".venv", "bin", "pip")
        if os.path.exists(venv_pip):
            run([venv_pip, "install", "--quiet", "-r",
                 os.path.join(install_dir, "requirements.txt")])
        log.info("auto-update applied: %s → %s", local[:8], remote[:8])
        return True
    except Exception:
        log.debug("auto-update check failed", exc_info=True)
        return False


def _restart_app():
    """Restart with a new PID so Control Center gets a fresh process identity."""
    # macOS 26 Control Center can retain the old process incarnation after
    # execv, then reject every status-item scene from the same PID. launchd's
    # KeepAlive.SuccessfulExit=false respawns this service on a nonzero exit.
    # A pre-rename install keeps running under the legacy label until logout.
    if os.environ.get("XPC_SERVICE_NAME") in (
            LAUNCH_AGENT_LABEL, LEGACY_LAUNCH_AGENT_LABEL):
        log.info("restarting after auto-update via launchd (new PID)")
        os._exit(75)
    # Manual installs have no supervisor. Spawn a separate process instead.
    subprocess.Popen([sys.executable] + sys.argv, start_new_session=True)
    log.info("restarting after auto-update in a new process")
    os._exit(0)

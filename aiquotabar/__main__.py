"""AIQuotaBar entry point."""

import os
import sys
import time

_lock_fd = None


def _single_instance(wait: float = 5.0) -> bool:
    """Hold an exclusive lock for the app's lifetime so only one copy runs.

    Waits briefly because a restart overlaps the old process: the updater's
    manual-run path spawns the new copy just before the old one exits. The fd
    is not inherited by child processes, so the spawned copy never holds it.
    """
    global _lock_fd
    import fcntl
    from aiquotabar.config import APP_SUPPORT_DIR
    fd = os.open(os.path.join(APP_SUPPORT_DIR, "aiquotabar.lock"),
                 os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return False
            time.sleep(0.2)
            continue
        _lock_fd = fd
        return True


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--history", "-H"):
        from aiquotabar.history import cli_history
        cli_history()
        return
    if not _single_instance():
        print("AIQuotaBar is already running.")
        # Exit 0 so launchd's KeepAlive (crash-only) doesn't respawn us.
        sys.exit(0)
    from aiquotabar.ui import ClaudeBar
    ClaudeBar().run()


if __name__ == "__main__":
    main()

# Menu bar disappearance: 2026-09-23

## Cause

Two bugs combined to leave the app fetching normally with no menu bar item:

1. The updater treated unequal local/remote hashes as an available update.
   Local HEAD `8260fbe` was ahead of `origin/main` (`be1622a`). A fast-forward-only
   merge of this ancestor returned success without changing HEAD, but the updater
   logged success and restarted anyway. The check repeats every four hours.
2. The restart used `os.execv`, preserving the PID. On this machine (macOS 26.6.2,
   build 25G83), Control Center retained the previous incarnation of that PID,
   flagged it as exiting, and rejected the replacement's status-item connection.

## Evidence collected before restarting

- PID 24202 was alive and writing fresh usage data at 13:06:02.
- A two-second `sample` showed a functioning AppKit event loop, not a deadlock,
  with repeated `NSSceneStatusItem _requestScene` calls.
- At 11:00:56.237 the application logged `auto-update applied: 8260fbec → be1622ad`
  followed by `restarting after auto-update`. Git confirmed HEAD was still
  `8260fbe`, with `origin/main` an ancestor.
- At 11:00:56.244 Control Center invalidated PID 24202's connection and marked
  its workspace as pending exit.
- At 11:00:59.724 Control Center reported that cached `24202(v4217C)` did not
  match the new `24202(v42E99)`, and cancelled the new connection because the
  workspace was exiting. This continued at 13:07.
- At 11:00:59.829 AppKit began reporting `scene activation failed`,
  `BSServiceConnectionErrorDomain Code=3`, and XPC reply errors.

This links the disappearance to in-place restart, rather than provider errors
or an unresponsive main thread. Restarting via launchd changes the PID, which
explains why previous manual restarts temporarily restored the icon.

## Fix

- Update only when HEAD is a strict ancestor of the fetched remote commit.
- Leave dirty working trees alone instead of silently stashing local fixes.
- Verify HEAD reached the target commit before reporting an update.
- For the managed service, exit nonzero and let its existing
  `KeepAlive.SuccessfulExit=false` LaunchAgent create a new process. For manual
  installs, spawn a fresh process. Never re-exec an AppKit process in place.

Regression coverage uses disposable local Git repositories for equal, ahead,
behind, divergent, dirty, untracked, and failed-fetch cases, plus both restart
paths without actually exiting the test process.

## Verification

- All 9 regression tests passed; Python compilation and `git diff --check` passed.
- Loaded the fix with a launchd restart at 13:10:41 (new PID 49592).
- At 13:10:43 Control Center logged `Bootstrap success!`, `Connection established`,
  and creation of a displayable instance in `.menuBar` for PID 49592. No identity
  mismatch or scene-activation failure appeared in the post-restart log check.
- Usage cache refreshed at 13:10:45. This verifies immediate recovery; a full
  four-hour update interval has not yet elapsed after the fix.

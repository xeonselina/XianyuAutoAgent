# Final review fixes

Base: `a2f59e8e8a447c042e0a007eb70bc00f3e02c298`

Implementation commit: `fix: resolve NAS release final review findings` (the commit containing this report; the exact hash is reported after commit creation).

## Finding evidence

1. Controlled DSM root `PATH`
   - `scripts/deploy_nas.sh` invokes the verified root-owned lifecycle script through `env -i` with `PATH=/usr/local/bin:/usr/bin:/bin` and `HOME=/root` for passwordless and password sudo.
   - Executing fake-SSH tests run the final root environment in both sudo modes and prove that the lifecycle receives the controlled path while credential and Make variables are absent.

2. Partial Compose stop failure
   - A nonzero current-release `stop worker app` now triggers one best-effort `up --detach --remove-orphans app worker` using `current.env`.
   - Recovery success/failure is reported separately, migrations do not run, and the original stop status is returned in both branches.

3. Same-tag metadata rotation
   - Promotion compares candidate/current `IMAGE_REF`. A same-tag deployment atomically refreshes `current.env` without changing `previous.env`; only a distinct image rotates version history.
   - Regression coverage proves migrations still run, prior metadata bytes remain unchanged, and no promotion journal is created for the same-tag path. Existing distinct-release promotion-failure recovery remains covered.

4. Promotion journal cleanup
   - Obsolete promotion-journal deletion is best-effort. Failure emits a warning, clears the active cleanup handle, and cannot prevent post-migration app/worker startup.
   - A failing fake `rm` verifies startup, health/probe completion, success output, and retained diagnostic journal.

5. Atomic root asset replacement
   - Uploaded assets move into a root-only staging directory on the deployment filesystem, receive final root ownership/modes, and are hashed before replacement.
   - Final Compose/script replacement uses same-filesystem `mv -f` rename, rejects symlink/directory targets after securing directory ownership/modes, and verifies final bytes. EXIT cleanup remains limited to the exact per-run user and root staging paths.

6. Disk-space preflight
   - `MIN_FREE_SPACE_MB` is configurable and defaults to `1024`. POSIX-style `df -Pk` checks the deployment filesystem and the Docker storage filesystem discovered with `docker info` before pull, network mutation, or service stop.
   - Low-space tests cover both filesystems and prove no pull/stop/up occurs. Unavailable Docker-root discovery warns and continues after the deployment-filesystem check rather than guessing a Synology path.

7. Base-10 health attempts
   - `HEALTH_ATTEMPTS` now accepts only `[1-9][0-9]*`; `08` is rejected before Docker or destructive work, eliminating Bash octal interpretation.

8. Safe success summary
   - A successful deploy obtains app/worker Compose state first, then prints the new image, the previous distinct image (or an explicit sentinel), container state, and `make nas-logs LOG_TAIL=200`.
   - Tests assert the complete summary and absence of the production env path and a literal secret value.

## Verification

- Relevant regression suite: `98 passed, 79 warnings`.
- `bash -n InventoryManager/scripts/deploy_nas.sh InventoryManager/deploy/nas/remote_release.sh`: passed.
- Make dry-runs for `check-nas`, explicit-tag `deploy-nas`, and `release-nas`: passed.
- `openspec validate add-nas-release-automation --strict`: passed.
- `git diff --check`: passed.
- Credential/private-key Git scan over `InventoryManager` and `docs/deployment`: no matches.
- Local Compose CLI was unavailable; Compose structure/configuration remains covered by the static pytest contracts.

## Residuals

- OpenSpec tasks 4.3 and 4.4 remain intentionally open: real Synology read-only discovery and the authorized first production release require operator access, a verified backup, and a maintenance window.
- When Docker storage discovery is unavailable, only the known deployment filesystem is enforced and the warning must be reviewed before production release.

## Round 2 credential-boundary fix

Implementation commit: `fix: isolate sudo authentication from root commands` (the focused commit containing this round; exact hash reported after commit creation).

- Each password-sudo SSH command has a dedicated authentication phase whose only operation is `sudo -S -p '' -v`. Authentication and execution stay in one remote shell so DSM sudo timestamp policies remain effective.
- After authentication the remote shell executes `exec </dev/null`; only then does root asset install, lifecycle execution, or exact staging cleanup run through `sudo -n`. Cached/NOPASSWD unread bytes are therefore closed before the privileged action starts.
- All three privileged action types now start with `env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/root`; only the lifecycle receives the validated non-sensitive release variables.
- The executing fake-SSH harness models cached/NOPASSWD sudo by deliberately not reading authentication stdin. In password and passwordless modes it executes install/lifecycle/cleanup probes and proves zero privileged-command stdin bytes, a controlled root PATH/HOME, and no credential or Make variables.
- Failure-path coverage proves a lifecycle status of 41 remains the final status while password-mode root cleanup and user-temp cleanup still run through their separated stdin boundaries.

Round 2 verification uses the same syntax, Make dry-run, strict OpenSpec, diff, and secret-scan commands listed above. The expanded relevant regression suite completed with `99 passed, 79 warnings`.

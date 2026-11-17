# github-auto-repository

A GitHub Actions dispatcher tests the full lifecycle of a private calculator repository. The shipped configuration keeps live automation off. You can run the tests, open the calculator, and preview the scheduler without credentials.

## Try it locally

Install Python 3.12 and Git. Open a terminal in this folder. On Windows PowerShell run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python main.py --dry-run
```

On macOS or Linux use `python3.12 -m venv .venv` and replace `.\.venv\Scripts\python` with `.venv/bin/python`. Git tests create temporary local repositories. All GitHub API tests use mocks. Open `calculator/index.html` directly in a browser. The calculator evaluates operations as entered, uses % to divide the displayed value by 100, and retains the last 50 calculations until the page reloads. Enter evaluates, Escape clears, and Backspace removes a digit.

## Deploy and preview

1. On GitHub create an empty **personal** repository named `github-auto-repository`. A private controller keeps the schedule and audit records private. Use an account you administer, preferably a dedicated testing account, and restrict write access to the controller.
2. From this project folder run the commands below, replacing YOUR-LOGIN. Use Git's normal sign-in flow. Keep secrets out of the repository.
3. The last command initializes the dedicated ledger branch from the supplied empty ledger. Run it only for initial setup. Never reset that branch to main. Protect it against deletion and force pushes. Permit the workflow's built-in GitHub token to push ordinary commits. If repository or organization rules require pull requests for every branch, arrange a narrow exception for this state branch.
4. In **Actions → Repository lifecycle → Run workflow**, select the default branch and leave **Preview** checked. Open the Dispatch step to see the plan. A preview reads existing state but never claims a slot or saves a hypothetical new plan. Two previews of an uninitialized day can therefore differ.

```sh
git init -b main
git add .
git commit -m "Add repository lifecycle dispatcher"
git remote add origin https://github.com/YOUR-LOGIN/github-auto-repository.git
git push -u origin main
git push origin main:automation-state
```

## Connect the account

Two credentials serve different purposes. The personal access token authenticates the owner, creates repositories, and writes the calculator. A private GitHub App issues short-lived deletion credentials restricted by GitHub to the **one numeric repository ID** in the creation receipt. This prevents a rename or replacement from redirecting a deletion to a different repository between the last check and the API call.

1. In your personal **Settings → Developer settings → Personal access tokens → Fine-grained tokens**, generate a token with your personal account as resource owner and **All repositories** so it covers future test repositories. Grant repository **Repository creation: write**, **Contents: read and write**, and the automatically included metadata access. GitHub also accepts Administration write for creation if your account lacks the narrower creation permission. Choose an expiration and plan to rotate before then. [Create repositories](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user) · [Upload contents](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
2. In the controller's **Settings → Secrets and variables → Actions → Secrets**, add the token as `GH_AUTOMATION_TOKEN`.
3. In personal **Settings → Developer settings → GitHub Apps → New GitHub App**, choose a unique name, use the controller URL for the homepage, disable webhooks, and select installation only on your account. Grant repository **Administration: read and write** with the automatically included Metadata permission. Install the App on your personal account with **All repositories** to cover future creations. Keep its private key secret because it can mint installation tokens. [Deletion permissions](https://docs.github.com/en/rest/repos/repos#delete-a-repository) · [Installation token scoping](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)
4. From the App settings, generate a private key. Copy the entire PEM, including its header and footer, into the controller's Actions **secret** `DELETION_APP_KEY`. Put the App's **Client ID** in the Actions **variable** `DELETION_APP_CLIENT_ID`. The runner signs locally using Ubuntu's OpenSSL. No OAuth callback or server is needed.
5. The workflow receives a separate built-in `GITHUB_TOKEN` with controller contents write access for ledger commits and configuration reads. GitHub supplies it automatically. Do not put personal credentials in YAML, shell commands, or logs.

## Explicitly activate or stop

1. Review `config.yaml`. When ready for live testing, commit `automation.enabled: true` and `security.dry_run: false` to the default branch. These are nested YAML keys. All other defaults can stay as supplied.
2. Give initial approval by creating the Actions **variable** `LIVE_APPROVAL` with the exact controller name, such as `octocat/github-auto-repository`. The scheduled job is skipped while this variable is absent. Manual live dispatch uses the same gates and honors the next eligible slot.
3. **Emergency stop:** cancel any running job in Actions, clear `LIVE_APPROVAL`, and commit `enabled: false` to the default branch. The worker rereads the default-branch configuration before mutations. A change stops subsequent writes. A request already accepted by GitHub can finish. Review the ledger for a partially completed run before resuming.
4. For credential revocation, delete the PAT in your personal developer settings, suspend or uninstall the deletion App, and revoke its private key. Remove the corresponding Actions secrets. Removing only an Actions secret does not revoke the underlying credential.

## Schedule and execution

The workflow polls at minutes 7, 27 and 47 of each hour. GitHub **cannot guarantee execution at an exact scheduled minute**. Scheduled jobs run from the default branch and can be delayed or dropped. Public repositories can have schedules disabled after extended inactivity. The controller runs in GitHub's cloud while your computer is off. [Scheduled workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

The first live poll each local day commits the entire plan. The scheduler weights counts near `target_daily_average` more heavily, excludes the previous planned count by default, and samples a random instant in each of several windows across the actual local day. It reserves the minimum spacing between windows, including across midnight. It uses elapsed seconds across daylight-saving transitions. Ten is the approximate average **planned** count. Delays, shutdowns and failures can reduce completions.

Edit the nested `automation` settings on the default branch to change `min_daily_runs`, `max_daily_runs`, `target_daily_average` or `minimum_interval_minutes`. Use a maximum of 15, choose a target inside the range, and leave enough minutes for all slots on a short day. A fixed count requires `different_count_each_day: false`. New schedule settings take effect on the next unplanned day. Recovery uses the current safety settings. Change the prefix or calculator only with no execution in progress. Private repositories, recorded identity checks, concurrency of one, and randomized scheduling are enforced.

Use an IANA timezone such as `America/Los_Angeles` or `Europe/London`. For an existing ledger, finish active work and disable automation for at least 24 hours after the last start. Resume when the new local date exceeds the most recent stored date. This avoids double-counting a day during migration. The log displays UTC offsets explicitly.

A dispatcher handles at most one lifecycle. It claims a slot before any creation, saves the creation intent, and records a receipt from a successful create response. It uploads the same HTML through the Contents API, reads the commit and compares the file bytes at that exact commit. After the configured wait (60 seconds by default), it checks the receipt, owner ID and login, exact name, prefix, creation timestamp, unique description, privacy, and controller name and ID. It mints a single-repository installation token, verifies that scope, repeats identity verification, deletes and confirms absence. Slot starts must also meet the actual-time spacing rule. Stale slots become missed after one configured interval. Previous days' slots never accumulate into a catch-up queue.

## State, monitoring and recovery

Open the **automation-state** branch and select `lifecycle-state.json`. The date keys are local schedule dates. Each row has a unique execution ID, planned and actual Unix timestamps, phase, repository name and creation receipt, upload and commit verification flags, deletion status, duration in seconds and error. A null receipt means creation was never confirmed. Skipped slots have no actual time. Actions logs include daily counts and observed API usage and rate-limit headers. An interrupted runner can undercount requests. Check the branch history to inspect earlier checkpoints.

A workflow-wide concurrency group serializes scheduled and manual runs. Each checkpoint is a Git commit and ordinary fast-forward push. A stale writer stops before the next mutation. A checksum detects accidental edits or truncation. Trusted branch writers can replace both data and checksum, so protect the branch and its history. The ledger grows with activity. Monitor its size and preserve history when planning archival. Caches and expiring artifacts are unsuitable as the sole record of creation.

- **Interrupted after claiming:** the next dispatcher resumes one active execution first. An expired claim is skipped. After verification the saved deadline survives runner cancellation.
- **Missing create response:** the next poll checks the exact name and records failure. Without a durable successful creation response, automatic cleanup stops even if the name exists. Inspect the run and GitHub activity manually.
- **Ambiguous upload or delete:** the worker reads commit/file state or current repository identity before proceeding. A missing repository after an unacknowledged deletion is recorded for review. Only an acknowledged deletion followed by absence counts as successful.
- **Identity or scope mismatch:** inspect the receipt and the repository in GitHub. A failed safety check can leave a temporary repository in place. No sweep by prefix is performed.
- **403, 429 or network errors:** check the PAT expiration, App installation, permissions, reset time and Actions logs. Reads have bounded backoff. Writes are single attempts with checkpoints. Repeated API failures can leave a failed run requiring manual review.
- **Missing branch, checksum mismatch or rejected push:** stop live dispatch, inspect branch history, and restore a verified ledger reconciled with actual repositories. Restoring an old snapshot blindly can replay already consumed slots. Re-enable only after reconciliation.
- **No eligible execution:** inspect the UTC timestamps and latest status. A manual live invocation also respects spacing and missed-slot rules. Never reset the ledger to force an execution.

## Usage and cost

At the shipped polling cadence there are up to 72 scheduled jobs per day after approval, about 2,160 in a 30-day month, plus roughly 300 one-minute retention waits if ten runs complete each day. Provisioning, dependency installation, API work, time rounding and retries can add usage. Idle polls exit after checking state. Standard hosted runners in public repositories are free under GitHub's current billing rules. Private controllers draw on plan allowances and may incur charges. Review **Settings → Billing and licensing** and configure a budget before activation. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)

Use the system only for repository lifecycle testing. Keep within account quotas and platform limits. The dispatcher has no contribution-statistics or evasion features.


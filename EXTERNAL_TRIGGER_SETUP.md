# External 5-Minute Trigger Setup

## Read-only diagnosis and account results

Both attendance workflows expose `dry_run`. Use **BJMF Manual Force Check** with `dry_run=true`, empty `notice_text` and empty `direct_punch_url` to check cloud account access without submitting attendance. Normal schedules still submit when they identify a valid task.

Both workflows now use the same `bjmf-attendance` concurrency group to avoid overlapping manual and scheduled submissions. Per-account summaries distinguish already signed, confirmed submission, missing task URL, cooldown, login required, unreadable page, rejected submission and unknown submission result. An overall failed run can still contain an account that succeeded.

The external scheduler may dispatch every 5 minutes. The checker applies its class-cycle gate and normally performs a single check at an allowed time.

Why this exists:

- GitHub Actions `schedule` can be delayed or skipped.
- `cron-job.org` can call `workflow_dispatch` every 5 minutes as a second trigger source.
- `BJMF_SAFE_SINGLE_CHECK=true` disables the legacy watch loop. Blank external dispatches follow the 10-minute class-cycle checkpoints and break-time gate.

## 1. Create a GitHub token

Create a fine-grained GitHub personal access token for this repository only:

- Repository: `llf48/AutoCheckBJMF-private`
- Permission: `Actions: Read and write`
- Optional metadata permission may be read-only.

Do not paste the token into the repository.

## 2. Create a cron-job.org job

Create a new job at <https://cron-job.org/>.

Use these settings:

```text
URL:
https://api.github.com/repos/llf48/AutoCheckBJMF-private/actions/workflows/AutoCheckBJMF.yml/dispatches

Method:
POST

Schedule:
Every 5 minutes

Timezone:
Asia/Shanghai
```

Headers:

```text
Authorization: Bearer YOUR_GITHUB_TOKEN
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
User-Agent: bjmf-external-trigger
```

Body:

```json
{
  "ref": "main",
  "inputs": {
    "watch_minutes": "5",
    "watch_interval_seconds": "30"
  }
}
```

Expected successful response:

```text
204 No Content
```

## 3. Keep GitHub schedule enabled

The built-in GitHub schedule is still enabled. Its exact checkpoints are defined in `AutoCheckBJMF.yml`; they are not an all-day 5-minute polling loop.
The external trigger is a backup for missed GitHub schedules.

## 4. How to check whether it worked

Open:

```text
https://github.com/llf48/AutoCheckBJMF-private/actions/workflows/AutoCheckBJMF.yml
```

You should see `workflow_dispatch` runs every 5 minutes while the cron-job.org job is active.

Open the run's per-account summary. A successful process or an `already_signed` observation does not establish a new submission. Submission evidence contains:

```text
post_attempt
post_response (submission_status=confirmed)
account_check_finished (outcome=submitted_confirmed)
```

Audit artifacts are named `bjmf-audit-<run_id>-<run_attempt>` and retained for 30 days. `needs_punch_url` means the active task did not expose a usable task ID; provide a valid URL from that task instead of re-running the same failing check repeatedly.

The separate `Offline regression tests` workflow runs mocked tests without attendance secrets. A green result there is a code-test result, not an attendance result.

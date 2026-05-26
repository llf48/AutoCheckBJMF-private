# External 5-Minute Trigger Setup

This repository now supports short watcher runs that are safe to trigger every 5 minutes.

Why this exists:

- GitHub Actions `schedule` can be delayed or skipped.
- `cron-job.org` can call `workflow_dispatch` every 5 minutes as a second trigger source.
- Each run watches for 5 minutes and checks every 30 seconds.

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

The built-in GitHub schedule is still enabled and runs every 5 minutes during the China-time watch window.
The external trigger is a backup for missed GitHub schedules.

## 4. How to check whether it worked

Open:

```text
https://github.com/llf48/AutoCheckBJMF-private/actions/workflows/AutoCheckBJMF.yml
```

You should see `workflow_dispatch` runs every 5 minutes while the cron-job.org job is active.

If a sign-in is active, the log should show lines like:

```text
Found GPS punch ids: ['...']
签到成功
Found and submitted 1 punch task(s). Ending watch.
```

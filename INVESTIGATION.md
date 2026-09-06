# Execution-source investigation (2026-09-06)

## Verified historical evidence

Reviewed 413 retained daytime runs spanning 2026-08-31 through 2026-09-04, plus the three earlier attempts of two rerun workflows. Dates below use China time.

- **2026-09-01 10:04, run 33461154824:** `BJMF Manual Force Check` ran `cloud_check.py` at revision `721bbac`. The list exposed task ID `5503957`; the POST response printed `签到成功`. The run completed successfully. This is direct evidence of a cloud submission.
- **2026-09-02:** account 1 was observed signed around 08:00 and 09:40. Those observations did not contain a new POST.
- **2026-09-03 09:40, run 33704575576:** account 1 was already signed; account 2 still had an active task without a parseable ID. The error was `1 of 2 cookie account checks failed`. This explains a red workflow alongside a successful account 1 attendance state.
- **2026-09-03:** both accounts were observed signed around 08:10 and 14:30. These observations alone cannot attribute the submissions.
- **2026-09-04 09:40, run 33826635666:** both accounts had an unparseable QR task, even after the fallback list request. Audit records contained no POST attempts. At 09:50, run 33827249564 observed both signed, again without a POST attempt.

Run links follow `https://github.com/llf48/AutoCheckBJMF-private/actions/runs/<run_id>`.

The retained evidence confirms one cloud submission and multiple other signed-state observations. It does **not** identify the submitting process for every historical observation. Missing local process/POST logs cannot be reconstructed from source code or present-day configuration.

## Entry points inspected

| Entry point | Configuration | Activation | Evidence limits |
| --- | --- | --- | --- |
| `cloud_check.py` | `BJMF_COOKIE` and numbered cookie secrets | Two attendance workflows; scheduled or externally dispatched | Audit records began on September 3, after the morning incidents |
| `main.py` | `config.json` in the working directory | Local manual, scheduled, or polling run | Previously persisted no audit when debug was off |
| Public local copy's `auto.py` | Invokes its adjacent `main.py` | Only after someone starts its loop | The wrapper starts a new child every five minutes; its presence does not prove it ran historically |

The current Documents and Public local configurations contain one account. The Documents local runner uses its legacy HTTP list and POST routes; the cloud runner uses HTTPS and a different discovery path. These are not equivalent configurations. No running attendance process, matching Windows scheduled task, or saved BJMF environment variables was found during this inspection. Current on-disk configuration cannot establish an old process's in-memory state.

## Corrected defects

These are reproduced code defects and observability improvements, not proof that a particular defect caused every historical QR miss. The user's report that GitHub completed QR attendance is not disproved by the absence of a matching submission in the retained runs.

- Removed a duplicate, overridden `check_one_cookie` implementation that obscured the actual cloud entry point.
- Added explicit per-account outcomes: already signed, no task, dry run, submitted and confirmed, missing task URL, rejected, unknown, or partial failure.
- Replaced course-wide verification with exact-task verification; an unrelated historical signed task no longer proves the target was signed.
- Preserved explicit server-confirmed success if the follow-up query times out. Unknown responses remain unknown, and explicit rejections remain failures.
- Prevented signed cards from contributing old task IDs for resubmission, and prevented signed siblings from hiding an unparsed active card.
- Added validation of submission origin, course, and account-specific numeric `sid` values before using a shared direct link.
- Added persistent redacted local auditing independent of debug mode, including source, script path, process ID, script hash, account, POST attempt, and server response.
- Corrected the local retry tuple handling and restricted automatic retries to connection/read failures before any POST. A rejected or uncertain POST is not immediately resent.
- Removed the local no-task `本次签到圆满成功` claim, and prevented notification failures from overturning confirmed attendance.
- Added per-account GitHub summaries, unbuffered output, and run-attempt-specific artifacts. Updated outdated scheduler documentation.
- Unified discovery of supported GPS/QR submission routes, explicit `data-punch-id` fields and hidden `punch_id` inputs. Decode HTML entities and escaped JSON URL slashes without executing JavaScript.
- Do not turn another origin/course's link into a guessed local submission, or resubmit ended cards. A form cannot switch the task ID.
- A missing-ID card no longer prevents processing another independently identified task; the final account result remains a partial failure if any task is unresolved.
- Capture account-scoped GET attempts, response status, page fingerprints, task types/timestamps, and action-first structural hints. Never retain raw HTML, hidden token values, or JavaScript handler bodies.
- Distinguish cooldown, login redirection, unreadable pages, server-declared prior attendance, and uncertain POST results. A generic page error is not proof of cookie expiry.
- Disable automatic POST redirects and restrict GET redirects to the same trusted endpoint. Read-only mode also blocks POST at the submission function itself.
- Both attendance workflows share one concurrency group. Each offers `dry_run` for read-only diagnostics; the normal scheduled behavior and account secrets are unchanged.

## Read-only cloud validation

Use **BJMF Manual Force Check**, select **dry_run**, and leave the notice and direct link empty. This reads each account's existing task list, writes per-account results and uploads sanitized audit evidence without attendance POST requests. A green result with no active tasks is a configuration/read-path check, not proof that a future QR task will be signed.

The offline test workflow does not use attendance credentials and runs the regression suite on code/workflow pushes.

## Remaining operational limitation

An active QR task whose list and fallback HTML expose neither its task ID nor a valid submission URL cannot be automatically submitted from those pages. The code reports `needs_punch_url` and requires the actual task URL. The fixes above do not invent missing QR credentials or retroactively prove historical submission sources.

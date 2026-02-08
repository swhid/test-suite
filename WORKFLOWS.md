# GitHub Actions Workflows

This document describes the CI workflows and recent fixes to the multi-platform test workflow.

## Workflow: SWHID Test Suite (Multi-Platform)

**File:** `.github/workflows/test-multi-platform.yml`

**Triggers:** Nightly at 2:17 AM UTC (`schedule`) and manual `workflow_dispatch`.

**Behavior:** The workflow first runs a `check-changes` job that compares current upstream state (test-suite SHA, swhid-rs main SHA, swh.model/swh.core versions, swhid gem version) to the state saved in the **most recent successful run’s** `upstream-state` artifact. If nothing changed, the workflow skips the `test` job (and thus the full matrix including Ruby) to save resources. Manual runs can override this with the **Force run tests** input.

---

## Recent Fixes (changes_detected and test runs)

The following three fixes were applied so that tests run when intended and failures are visible.

### Fix A: Use most recent successful run for upstream-state comparison

**Changes:**

- In the “Find previous workflow run” step, the workflow now uses **`workflow_runs[0]`** (the most recent successful run) instead of **`workflow_runs[1]`** (the second-most-recent) when selecting which run’s `upstream-state` artifact to download.
- The “need at least 2 runs” check was relaxed to **“need at least 1 successful run”** (`length >= 1`). The step still verifies that the chosen run has an `upstream-state` artifact.
- Log messages were updated to say “most recent successful run” instead of “previous run”.

**Motivation:**

- “No upstream changes” should mean “unchanged since the **last** successful run.” Using `[1]` compared against the wrong run’s state, which could cause tests to be skipped when they should run, or the opposite. Using `[0]` aligns behavior with that intent.
- Requiring only one successful run allows the first run that produces `upstream-state` to be used on the next run, without needing a second historical run.

**Expected results:**

- Each run compares current state to the **last** successful run’s saved state.
- Tests are skipped only when nothing has changed since that run; they run when test-suite, swhid-rs, or package/gem versions have changed (or when there is no previous state).

---

### Fix B: Fail check-changes when “Check for upstream changes” errors

**Changes:**

- **Removed** `continue-on-error: true` from the “Check for upstream changes” step (the step with `id: check-changes` that runs the bash script and writes `changes_detected` to `GITHUB_OUTPUT`).
- Other steps in the job (e.g. “Set up Python”, “Find previous workflow run”, “Upload current state”) keep their existing `continue-on-error` where appropriate.

**Motivation:**

- If the check script failed (e.g. script error, missing tool), the step previously did not fail the job and often did not set `changes_detected`. The test job’s condition `changes_detected == 'true'` was then false, so tests were **silently skipped**.
- Making the step fail the job ensures that any failure in the upstream check is visible (red run) and is not mistaken for “no changes detected.”

**Expected results:**

- Any failure in “Check for upstream changes” fails the `check-changes` job and the workflow run.
- Failures are visible in the Actions UI instead of resulting in skipped tests with no explanation.

---

### Fix C: Add workflow_dispatch “Force run tests” input

**Changes:**

- Added a `workflow_dispatch` input:
  - **Name:** `force_run`
  - **Type:** boolean
  - **Default:** false
  - **Description:** “Force run tests even when no upstream changes detected”
- **test** job: the condition is now  
  `needs.check-changes.outputs.changes_detected == 'true' || github.event.inputs.force_run == 'true'`.
- **publish-dashboard** job: the condition is now  
  `github.ref == 'refs/heads/main' && (needs.check-changes.outputs.changes_detected == 'true' || github.event.inputs.force_run == 'true')`.

**Motivation:**

- Scheduled runs should keep the current optimization (skip tests when no upstream changes).
- Manual “Run workflow” runs should be able to run the full test matrix (including Ruby on all OSes) even when no upstream changes are detected, e.g. for debugging or ad-hoc validation.

**Expected results:**

- **Scheduled runs:** Unchanged. Tests run only when `changes_detected == 'true'` (no input is set).
- **Manual runs:** In the Actions “Run workflow” dialog, checking “Force run tests even when no upstream changes detected” runs the test job (and, on main, publish-dashboard) even when `changes_detected` is false.

---

## Other workflows

- **test-ubuntu.yml** – Ubuntu-only test workflow (e.g. for branch runs).
- **bisect.yml** – Bisection workflow (manual trigger).

For details, see the workflow files under `.github/workflows/`.

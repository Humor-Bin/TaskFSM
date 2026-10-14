---
name: taskfsm-worker
description: Execute a TaskFSM-managed task through Codex while keeping TaskFSM as the authoritative lifecycle controller.
---

# TaskFSM Worker

Use this skill when `TASKFSM_TASK_ID` is present or when the user explicitly asks you to work on a TaskFSM-managed task.

## Core rule

TaskFSM owns the business task lifecycle. Your internal plan/todo list is execution detail only. Never infer that the TaskFSM task is complete just because your local plan is complete.

## Required workflow

1. Call the TaskFSM MCP tool `get_current_task` before making changes.
2. Read the repository's `AGENTS.md` and follow repository-local development rules.
3. Keep your own plan as detailed as needed, but do not create or mutate TaskFSM state except through TaskFSM MCP tools.
4. Call `heartbeat` during long-running work.
5. Call `report_progress` only at meaningful execution milestones. The progress value is a coarse human-facing estimate, not a count of your internal todo items.
6. Run the project's required tests and verification commands.
7. Submit concrete outputs with `submit_artifact` (for example a git commit, PR URL, patch, file, test report, or generated document).
8. Only after required artifacts exist and verification has passed, call `request_review`.
9. If TaskFSM rejects a transition, treat the rejection as authoritative and resolve the stated guard condition instead of bypassing it.

## Observed sessions

If `TASKFSM_TASK_ID` is absent, you may be running in TaskFSM Observe Mode. In that mode do not attempt to claim, mutate, or complete a TaskFSM task. TaskFSM reads the native Codex session and projects it read-only.

## Information boundaries

Expose observable execution facts: plan steps, tool/command events, changed files, tests, artifacts, errors, and status. Do not expose hidden chain-of-thought or private reasoning.

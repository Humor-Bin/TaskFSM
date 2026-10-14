# TaskFSM Platform Implementation Plan

> **For agentic workers:** implement task-by-task, keep the spec authoritative, and use tests as the per-task completion gate.

**Goal:** Deliver a working TaskFSM modular-monolith backend, live frontend integration and Python Agent SDK.

**Architecture:** FastAPI + SQLAlchemy domain services with action-driven FSM and persisted events. SSE supplies realtime UI updates. The web runtime console is served as static assets and reads dashboard/API data.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, Pydantic, httpx, pytest, vanilla ES modules.

**Spec:** `docs/superpowers/specs/2026-10-13-taskfsm-platform-design.md`

## Global Constraints
- Agents never PATCH task status directly.
- State changes occur only through named actions and guards.
- Successful mutations create persisted events.
- SQLite works out of the box; PostgreSQL is supported through `DATABASE_URL`.
- Frontend copy remains Chinese.
- Agent runtime mutation calls require the registered Bearer token.
- Browser UI must not impersonate an Agent.

## Review Focus
- stale/expired lease cannot mutate a task
- dependency guard blocks readiness/completion when dependencies are not done
- review cannot complete without approval
- capability filtering excludes incompatible agents/tasks
- SSE subscriber cleanup and cross-thread publication
- missing/wrong Agent token is rejected

## Delivered tasks

### Task 1: Domain state machine
- [x] Guard tests
- [x] Action-driven transitions
- [x] Illegal in_progress -> done rejection

### Task 2: Persistence models and services
- [x] Task / Agent / Lease / Run / Artifact / Review / Event models
- [x] Task dependencies
- [x] Transactional domain services and event persistence

### Task 3: Agent runtime, lease and run
- [x] Register and hashed token authentication
- [x] Capability-filtered discovery
- [x] Claim creates Run + Lease
- [x] Agent and lease heartbeat
- [x] Expired lease sweep

### Task 4: Artifact and review lifecycle
- [x] Active-lease artifact guard
- [x] Agent request-review action
- [x] Human review record
- [x] Approval guard before completion

### Task 5: Realtime and dashboard API
- [x] Dashboard aggregate endpoint
- [x] Persisted event list
- [x] SSE stream
- [x] Thread-safe in-process broker

### Task 6: Python Agent SDK and example worker
- [x] Registration/token handling
- [x] Discovery, claim, heartbeat, progress, artifact, review methods
- [x] Example worker

### Task 7: Live web integration
- [x] Chinese runtime console
- [x] `/api/dashboard` mapping
- [x] SSE refresh
- [x] explicit offline demo mode
- [x] human review/complete flow
- [x] browser Agent-impersonation prevention

### Task 8: Packaging, Docker and documentation
- [x] requirements and environment example
- [x] Dockerfile / Compose with PostgreSQL and reserved Redis
- [x] README and functional documentation
- [x] GitHub Actions CI
- [x] backend, SDK and Web test suites

## Next-phase work
Human OIDC/RBAC, database migrations, Redis/NATS realtime backend, scheduler/retry policies, project/workspace isolation and concrete Codex/Claude adapters should be implemented as separate follow-up specifications rather than silently expanding the MVP boundary.

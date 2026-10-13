# TaskFSM Platform Design

## Goal
Build TaskFSM as a human-supervised control plane for AI Agent task execution. The platform must make task lifecycle, ownership, dependencies, leases, runs, artifacts, reviews and audit events observable and enforceable by the server.

## Product boundary
TaskFSM decides who may act, which state transitions are legal, whether guards pass, how ownership is leased, and what execution evidence exists. Agents decide how to perform work. Agents never write task state directly; they request actions and the server validates them.

## Architecture
A modular monolith is used for the first production-capable version:
- FastAPI API and static web host
- SQLAlchemy persistence, SQLite by default and PostgreSQL through `DATABASE_URL`
- event log persisted in the same database
- in-process realtime broker exposed through SSE; broker interface is isolated for later Redis/NATS replacement
- Python Agent SDK built on HTTP
- optional Docker Compose with PostgreSQL and Redis for deployment evolution

## Domains
### Task
Task contains title, description, priority, status, required capabilities, assignee, dependencies and timestamps.

### State machine
Canonical states: backlog, todo, ready, in_progress, review, blocked, done. Allowed transitions are action-driven and guarded. Direct `in_progress -> done` is forbidden.

### Agent
Agent registers identity, kind and capabilities. Registration produces an API token; only its hash is persisted. Agent runtime mutation endpoints require the matching Bearer token. Online status is derived from heartbeats.

### Lease
Claiming a ready task creates a lease. Only the lease owner may submit runtime progress, artifacts or review requests while the lease is active. Expired leases are swept and an in-progress task returns to ready.

### Run
Each claim creates an immutable execution run record. Retries create new runs instead of overwriting old history.

### Artifact
Artifacts are first-class records linked to a task and run. Supported generic types include file, url, git_commit, pull_request, report and json.

### Review
A review records reviewer identity, decision and reason. Approval is required before review -> done.

### Event
Every externally meaningful action creates an event with entity, actor, payload and timestamp. Current state and event history coexist; this is event-driven audit, not full event sourcing.

## Agent protocol
Minimum operations:
1. register
2. agent heartbeat
3. discover available tasks by capabilities
4. claim task
5. lease heartbeat
6. report progress
7. submit artifact
8. request review
9. release or block task

## API principles
- Human and Agent APIs share domain services but use explicit action endpoints.
- State transitions are never exposed as generic PATCH status mutations.
- Successful domain mutations persist an Event and publish the corresponding realtime envelope after commit.
- Dashboard endpoints return frontend-ready snapshots to reduce client fan-out.

## Realtime
`GET /api/events/stream` uses SSE. Events are JSON envelopes with monotonically increasing DB IDs. The in-process broker supports thread-safe publication from FastAPI worker threads and cleans up subscribers. Multi-instance deployment should replace it with Redis Pub/Sub or NATS.

## Frontend integration
The approved Chinese runtime console is the primary UI. It reads `/api/dashboard`, subscribes to `/api/events/stream`, and falls back to an explicitly labelled local demo mode when the API is unavailable. Browser code does not impersonate an Agent; Agent-owned transitions such as request-review must originate from the Agent SDK.

## Security boundary
- Agent bearer credentials are implemented and token hashes are stored server-side.
- Human authentication is **not implemented in this iteration**. Human review/complete endpoints accept actor/reviewer fields as a development placeholder.
- OIDC/session authentication, organization/project membership and RBAC are required before an internet-facing production deployment.
- CORS is permissive for local development and must be restricted in production.

## Non-goals for this iteration
- autonomous multi-agent planning
- model hosting
- arbitrary remote code execution
- distributed event sourcing
- Kubernetes operator
- enterprise RBAC matrix

## Acceptance criteria
- Task state machine and dependency guards are unit tested.
- Agent can register, authenticate, discover, claim and heartbeat a task.
- Claim creates both lease and run.
- Artifact submission and review request require active ownership.
- Approval is required before completion.
- Every successful mutation emits a persisted event.
- SSE emits realtime event envelopes without cross-thread queue corruption.
- Existing web console can load live dashboard data and perform human review/complete actions.
- Local run, Docker deployment and Agent SDK instructions are documented.

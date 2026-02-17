# Durable Orchestrator Migration Plan
Last updated: 2026-02-17

## Goal
Migrate from JSONL daemon-only orchestration to durable Postgres-backed workflow execution without breaking current production behavior.

## Current Production Path (Rollback-Safe)
- Intake and processing remain on:
  - `email_work_order_service.py`
  - `intake_stream_processor.py`
  - `pipeline_daemon.py`
  - `publish_sender.py`
- Safety flag stays:
  - `AUTO_SEND_ENABLED=false`

## New Scaffold Introduced
- `orchestrator/` package:
  - `config.py`: env-backed orchestrator config.
  - `schema.sql`: initial Postgres schema (`workflow_runs`, `workflow_events`, artifact tables).
  - `store.py`: `InMemoryRunStore` and `PostgresRunStore`.
  - `stages.py`: legacy stage adapters (tier/context/draft/tone/fact/qa/policy/publish).
  - `runtime.py`: `DurableOrchestrator` runner with stage event persistence hooks.
- `orchestrator_runner.py`: one-shot runner for scaffold validation.
- `swarm_langgraph/` package:
  - `graph.py`: LangGraph graph (fallback executor if dependency missing).
  - `nodes.py`: specialist agents (tier/context/draft/tone/fact/qa/policy/publish).
  - `supervisor.py`: supervisor execution + artifact/event persistence.
  - `queue.py`: in-memory and Postgres `swarm_jobs` queue with retry/dead-letter.
  - `worker.py`: queue consumer loop for production worker service.
- `swarm_worker_runner.py`: swarm worker entrypoint.

## Migration Steps
1. Stand up Postgres and set `DATABASE_URL` in Railway.
2. Run `orchestrator_runner.py` in non-prod against copied/sample work orders.
3. Verify table writes and parity with JSONL outputs.
4. Add queue/event ingestion contract for run triggering (`swarm_jobs`).
5. Shadow-run orchestrator in production (no publishing side effects).
6. Cut over publish decisioning to Postgres-backed run state.
7. Keep legacy daemon available for fast rollback until two weeks of stable operation.

## Rollback Plan
- If orchestration errors or latency spikes:
  - disable new orchestrator worker
  - continue with existing `pipeline_daemon.py`
  - keep Zapier publish path unchanged

## Exit Criteria for Cutover
- Durable workflow records for all processed work orders.
- Stage-level observability from `workflow_events`.
- No regression in escalation safety behavior.
- Human review path unchanged.

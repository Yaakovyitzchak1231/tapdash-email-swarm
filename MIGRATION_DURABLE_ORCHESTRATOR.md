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
  - `graph_agents.py`: optional Graph/Outlook thread enrichment node.
  - `monday_agents.py`: Monday coordinator + subagents for contact/deal/update context.
  - `supervisor.py`: supervisor execution + artifact/event persistence.
  - `queue.py`: in-memory and Postgres `swarm_jobs` queue with retry/dead-letter.
  - `worker.py`: queue consumer loop for production worker service.
- `swarm_worker_runner.py`: swarm worker entrypoint.
- `swarm_ingest.py`: actionable stream -> `swarm_jobs` ingestion adapter with offset state.
- `swarm_publish_dispatcher.py`: DB publish queue dispatcher with idempotent status lifecycle.

## Migration Steps
1. [x] Stand up Postgres and set `DATABASE_URL` in Railway.
2. [x] Add queue/event ingestion contract (`swarm_jobs`) and worker loop.
3. [x] Deploy shadow swarm worker in Railway with draft-only mode.
4. [x] Verify durable writes in live shadow runs (`workflow_runs`, `workflow_events`).
5. [x] Add automatic ingestion from intake/work orders into `swarm_jobs`.
6. [x] Add DB-based publish dispatcher from swarm output to Zapier drafts.
7. [x] Add stuck-job reaper for stale `running` jobs.
8. [x] Add Graph thread enrichment and merge with Monday context.
9. [ ] Cut over publish decisioning to swarm DB-backed path.
10. [ ] Keep legacy daemon hot as rollback for two weeks after cutover.

## Remaining Work To Full Functionality (Execution Order)
1. Operational readiness:
   - queue depth/failure/dead-letter monitoring and alerts.
2. Cutover:
   - switch primary publish source to swarm path, preserve rollback toggle.

## Rollback Plan
- If orchestration errors or latency spikes:
  - disable new orchestrator worker
  - continue with existing `pipeline_daemon.py`
  - keep Zapier publish path unchanged

## Exit Criteria for Cutover
- Durable workflow records for all processed work orders.
- Stage-level observability from `workflow_events`.
- Automatic ingestion and publish dispatch running without manual DB inserts.
- No regression in escalation safety behavior.
- Human review path unchanged.

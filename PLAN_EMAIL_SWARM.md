# TapDash Email Swarm Master Plan
Last updated: 2026-02-17
Status: Active canonical plan (single source of truth)

## Purpose
This document is the implementation plan for the intelligent TapDash email swarm.
All roadmap, architecture, and delivery decisions should align to this file.

## Current Baseline (already running)
- Platform: Railway project `industrious-youth`, service `pipeline`.
- Ingress: `POST /zapier/email-forward` on the intake service.
- Processing: intake filter, work-order creation, policy tiering, multi-stage draft pipeline, publish sender.
- Persistence: JSONL files on attached volume `/data`.
- Outbound: Zapier webhook publish flow with metadata passthrough (`message_id`, `conversation_id`, sender/recipient fields, `send` flag).
- Keep-alive: scheduled ping via `.github/workflows/ping-railway.yml`.

## Problem Statement
The system now supports intelligent LLM drafting, but it still needs durable state, richer context sources (Graph + Monday), and cleaner worker decomposition.

## Progress Snapshot (2026-02-17)
## Completed
- Canonical plan and doc alignment:
  - `PLAN_EMAIL_SWARM.md` is source of truth.
  - README/deploy docs reference this plan.
- Multi-agent pipeline stages implemented in `pipeline_daemon.py`:
  - `context_agent`
  - `draft_agent`
  - `tone_agent`
  - `fact_agent`
  - `qa_agent`
  - `policy_agent`
  - `publish_agent`
- LLM drafting implemented:
  - OpenAI call in `draft_agent` with structured JSON output contract.
  - Confidence and rationale captured in downstream artifacts.
  - Template fallback path retained for resilience.
- Metadata passthrough maintained:
  - `message_id`, `conversation_id`, sender/recipient threading fields preserved into publish payloads.
- Safety controls implemented:
  - `AUTO_SEND_ENABLED` flag added.
  - Production currently configured with `AUTO_SEND_ENABLED=false`.
  - `publish_sender` now skips webhook sends when `send=false`.
- Signature control implemented:
  - Signature defaults to Yaakov identity (`Yaakov`, `yaakov@tapdash.co`).
  - Prompt enforces explicit signature and bans placeholder signatures.
- Test coverage:
  - Unit suite passing, including new tests for OpenAI draft path and no-send publish behavior.
  - End-to-end runs validated intake -> actionable -> draft -> escalation/publish artifact generation.

## In Progress
- Quality tuning for generated replies:
  - Implemented in this task:
    - Prompt hardening for stronger business tone and clearer CTA expectations.
    - Deterministic quality gate for generic fluff, missing actionable CTA, and weak personalization.
    - QA/policy integration so quality failures route to human review.
  - Remaining:
    - Expand regression examples and tune acceptance thresholds before enabling auto-send.
    - Calibrate prompts/heuristics against real inbox traffic and reviewer feedback.
- Durable orchestration pivot (started):
  - Added `orchestrator/` scaffold with stage runtime, Postgres schema, and storage interfaces.
  - Added migration/cutover document with rollback-safe strategy.
  - Added `swarm_langgraph/` supervisor + specialist runtime and queue worker scaffold.
  - Added `swarm_jobs` queue schema with retry/dead-letter lifecycle.

## Not Started
- Outlook/Graph thread retrieval and draft-in-thread publish path.
- Monday CRM enrichment in live context assembly.
- Queue/event-driven worker split beyond single daemon process.
- Human review dashboard/UX for escalations.

## Target State (what we are building)
- LLM-generated drafts, not canned templates.
- Multi-stage agent flow:
  - Intake
  - Context assembly (thread + CRM + precedent)
  - Draft generation
  - Tone/style QA
  - Fact/risk gate
  - Publish or escalate
- Durable state in Postgres (not file-only JSONL).
- Human escalation surface for low-confidence or policy-sensitive replies.

## Architecture Plan
## 1. Orchestration
- Commander pipeline controls lifecycle and observability per work order.
- Worker stages communicate through explicit events/states.
- Every stage appends provenance and confidence fields.

## 2. Data Model
- Core entities:
  - `work_orders`
  - `context_packs`
  - `drafts`
  - `qa_results`
  - `escalations`
  - `publish_queue`
  - `precedents`
- Required metadata in all downstream records:
  - `work_order_id`
  - `message_id`
  - `conversation_id`
  - `from_addr`
  - `to_addrs`
  - `cc_addrs`
  - `subject`

## 3. Integrations
- Outlook/Graph:
  - Fetch thread context using `message_id` and/or `conversation_id`.
  - Publish as draft or send in existing thread.
- Monday:
  - Enrich by sender email/domain (board `18397429943`).
- Zapier:
  - Continue as fallback publish path until Graph send is fully enabled.

## 4. LLM Drafting Spec
- Default model: `gpt-4.1-mini` (configurable).
- Prompt inputs:
  - thread context
  - sender/recipient info
  - subject/body
  - Monday enrichment
  - approved tone constraints
- Output contract:
  - `draft_subject`
  - `draft_body`
  - `confidence`
  - `rationale`
  - `citations`
- Tone constraints:
  - professional
  - concise
  - friendly undertone
  - no em dashes
  - clear CTA

## Delivery Plan (phased)
## Phase 1: Intelligent Drafting
- Replace canned text path in `pipeline_daemon.py` with OpenAI call.
- Add structured validation of model output.
- Gate auto-send by confidence and policy tier.
- Exit criteria:
  - drafts are LLM-generated
  - metadata passthrough remains intact
  - low-confidence outputs escalate
Phase status: Mostly complete.
Remaining for Phase 1:
- Improve output quality consistency.
- Tune QA gate thresholds and prompts using live traffic samples and reviewer feedback.

## Phase 2: Durable State
- Move pipeline state from JSONL to Postgres tables.
- Keep JSONL optional for local debugging only.
- Exit criteria:
  - end-to-end flow survives restart without state loss
  - workers can scale without shared-volume coupling
Phase status: In progress.
Current state:
- Postgres schema scaffold created (`orchestrator/schema.sql`).
- Durable runtime scaffold created (`orchestrator/runtime.py`, `orchestrator/store.py`, `orchestrator/stages.py`).
- LangGraph swarm scaffold created (`swarm_langgraph/*`, `swarm_worker_runner.py`).
Remaining:
- Wire queue-driven execution against Postgres in Railway.
- Migrate read/write paths from JSONL artifacts to DB-backed artifacts.
- Add replay/retry semantics per stage.

## Phase 3: Context Enrichment
- Add Graph thread retrieval and Monday enrichment into context pack.
- Persist enrichment and citations in provenance.
- Exit criteria:
  - draft quality clearly uses thread + CRM facts
  - publish payload carries full thread metadata
Phase status: Not started.

## Phase 4: Agentic Decomposition
- Split monolithic daemon into workers (intake/context/draft/qa/publish).
- Add queue/event-driven handoff.
- Exit criteria:
  - independent worker retries
  - per-stage monitoring and backlog visibility
Phase status: Partially complete.
Current state:
- Logical stages exist in code.
Remaining:
- Split into separate workers/processes with queue-backed handoff.

## Phase 5: Human Review Surface
- Add minimal escalation endpoint/view for approve/edit/reject.
- Feed approved edits into precedent memory.
- Exit criteria:
  - human reviewers can resolve escalations quickly
  - precedents reduce repeated escalations
Phase status: Partially complete.
Current state:
- Review action service exists and writes precedents.
Remaining:
- Build minimal dashboard/UI and triage workflow.

## Immediate Priorities
1. Finish Phase 1 quality hardening:
   - expand regression set and tune quality heuristics for production readiness.
   - finalize quality acceptance bar before enabling any auto-send path.
2. Keep safety-first outbound mode:
   - keep `AUTO_SEND_ENABLED=false` until output quality is approved.
3. Start Phase 2:
   - wire Postgres orchestrator scaffold into Railway shadow-run mode.
   - implement DB-backed artifact read/write parity checks vs JSONL.
4. Start Phase 3:
   - add Graph thread fetch and Monday enrichment to context assembly.

## Dependencies and Required Secrets
- `OPENAI_API_KEY`
- `ZAPIER_SHARED_SECRET`
- `PUBLISH_WEBHOOK_URL`
- `MONDAY_API_TOKEN`
- Optional for Graph path:
  - `GRAPH_TENANT_ID`
  - `GRAPH_CLIENT_ID`
  - `GRAPH_CLIENT_SECRET`

## Acceptance Criteria for "Intelligent Replies"
- Drafts are generated by LLM with defined tone constraints.
- Work-order context includes thread metadata and enrichment when available.
- Unsafe/uncertain drafts do not auto-send and are escalated.
- Publish payloads remain thread-aware for in-thread response creation.
- Plan status can be tracked directly from this document and linked references.

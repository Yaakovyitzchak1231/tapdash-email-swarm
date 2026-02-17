# Inbound Email -> Work Orders

> Canonical plan: `PLAN_EMAIL_SWARM.md` is the single source of truth for architecture and roadmap. This README documents the current implementation baseline only.
> Durable orchestration migration: `MIGRATION_DURABLE_ORCHESTRATOR.md` tracks the pivot plan and rollback-safe cutover path.

This service monitors inbound email events via HTTP and creates work orders with preliminary labels.

## Run

```bash
python3 email_work_order_service.py
```

Environment variables:

- `PORT` (default: `8080`)
- `WORK_ORDER_STORE` (default: `work_orders.jsonl`)
- `ZAPIER_SHARED_SECRET` (optional, if set then requests must include header `X-Webhook-Secret`)

## Send an email event

```bash
curl -X POST http://localhost:8080/email-events \
  -H 'content-type: application/json' \
  -d '{
    "event_id": "evt_1001",
    "sender": "ops@example.com",
    "subject": "URGENT: invoice payment failed",
    "body": "Our billing page returns an error"
  }'
```

Response includes the created work order. Persisted records are appended as JSON Lines in `WORK_ORDER_STORE`.

## Zapier Forwarding Endpoint

Use endpoint `POST /zapier/email-forward` from your Zap.

Accepted payload keys (best effort mapping):

- sender: `from_email` or `from`
- subject: `subject` or `topic`
- body: `body_plain`, `plain_body`, `body`, or `text`
- event id: `event_id`, `message_id`, `messageId`, or `id`

Example:

```bash
curl -X POST http://localhost:8080/zapier/email-forward \
  -H 'content-type: application/json' \
  -H 'X-Webhook-Secret: your-shared-secret' \
  -d '{
    "messageId": "msg_5001",
    "from_email": "client@example.com",
    "subject": "Need pricing",
    "body_plain": "Can we schedule a demo this week?"
  }'
```

## Event Shape

Expected payload keys for `/email-events` (all optional but recommended):

- `event_id`
- `sender`
- `subject`
- `body`

## Preliminary Labels

Current heuristic labels:

- `billing`, `support`, `urgent`, `sales`, `account` from keyword matches
- `government`, `education`, `consumer` from sender domain
- `general` fallback when no rules match

## Tiered Escalation Policy

Tier behavior is defined in `config/escalation_policy.json` and loaded by `escalation_policy.py`.

- Tier `A`: acknowledgments/scheduling, auto-publish allowed
- Tier `B`: safe operational language, auto-publish allowed
- Tier `C`: pricing/legal/security/compliance/guarantees, requires human review

Bootstrap or refresh default policy:

```bash
python3 -c "from escalation_policy import ensure_default_policy; ensure_default_policy()"
```

## Precedent Memory

Approval history is stored in `memory/precedents.jsonl` and used to reduce repeat escalations for known-safe patterns.

- Key format: `sender_domain|sorted_labels|policy_tier`
- Lookup logic: requires minimum sample size and confidence before auto-use

## Pipeline Auto-Runner

`pipeline_daemon.py` processes unseen records from `intake_state/actionable_work_orders.jsonl` and writes:

- `pipeline_out/context_packs.jsonl`
- `pipeline_out/drafts.jsonl`
- `pipeline_out/tone_checked.jsonl`
- `pipeline_out/fact_checked.jsonl`
- `pipeline_out/qa_results.jsonl`
- `pipeline_out/escalations.jsonl`
- `pipeline_out/draft_publish_payloads.jsonl`

Run one pass:

```bash
python3 pipeline_daemon.py --once
```

Run as daemon (polling):

```bash
python3 pipeline_daemon.py --interval-seconds 10
```

## Durable Orchestrator Scaffold (Phase 2 pivot)

New scaffold path (does not replace production daemon yet):

- `orchestrator/` package
- `orchestrator_runner.py`

Dry run (in-memory, no DB writes):

```bash
python3 orchestrator_runner.py --dry-run
```

Postgres-backed run:

```bash
DATABASE_URL=postgresql://... python3 orchestrator_runner.py
```

## Agent Swarm Worker (LangGraph path)

Draft-only swarm worker path (keeps legacy daemon as fallback):

```bash
DATABASE_URL=postgresql://... python3 swarm_worker_runner.py --once
```

Loop mode:

```bash
DATABASE_URL=postgresql://... python3 swarm_worker_runner.py --interval-seconds 10
```

## Human Review Actions API

Use `review_actions_service.py` to record human decisions and teach precedent memory.

Run:

```bash
python3 review_actions_service.py
```

Default port: `8090` (`REVIEW_PORT` env var to override).

Endpoints:

- `GET /health`
- `GET /escalations`
- `POST /review-action`

`POST /review-action` payload:

- `work_order_id` (required)
- `action` (required): `approve`, `edit_approve`, `reject`
- `reviewer` (optional)
- `edited_body` (required when `action=edit_approve`)

On approve/edit_approve:

- appends review event to `pipeline_out/review_actions.jsonl`
- writes precedent to `memory/precedents.jsonl`
- writes publish payload to `pipeline_out/draft_publish_payloads.jsonl` when missing

## Production Hosting

For always-on deployment with `systemd` and Cloudflare tunnel, use:

- `deploy/README.md`
- `deploy/install_services.sh`
- `deploy/install_cloudflared.sh`
- `deploy/systemd/*.service`

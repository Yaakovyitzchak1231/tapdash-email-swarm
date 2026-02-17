create table if not exists workflow_runs (
    run_id text primary key,
    work_order_id text not null unique,
    status text not null,
    current_stage text not null,
    created_at timestamptz not null,
    updated_at timestamptz not null
);

create table if not exists workflow_events (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    stage text not null,
    status text not null,
    needs_human_review boolean not null default false,
    payload jsonb not null,
    created_at timestamptz not null
);

create index if not exists idx_workflow_events_run_id_created_at
    on workflow_events(run_id, created_at desc);

create table if not exists context_packs (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null,
    created_at timestamptz not null
);

create table if not exists drafts (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null,
    created_at timestamptz not null
);

create table if not exists qa_results (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null,
    created_at timestamptz not null
);

create table if not exists escalations (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null,
    created_at timestamptz not null
);

create table if not exists publish_queue (
    id bigserial primary key,
    run_id text not null references workflow_runs(run_id) on delete cascade,
    work_order_id text not null,
    payload jsonb not null,
    created_at timestamptz not null
);

create table if not exists swarm_jobs (
    job_id text primary key,
    work_order_id text not null unique,
    payload jsonb not null,
    status text not null check (status in ('queued', 'running', 'done', 'dead_letter')),
    attempt integer not null default 0,
    max_attempts integer not null default 3,
    available_at timestamptz not null default now(),
    locked_at timestamptz null,
    worker_id text null,
    last_error text null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_swarm_jobs_status_available
    on swarm_jobs(status, available_at);

create index if not exists idx_swarm_jobs_locked_at
    on swarm_jobs(locked_at);

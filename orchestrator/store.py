from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .models import StageResult, WorkflowRun, utc_now_iso

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

if TYPE_CHECKING:
    import psycopg


class RunStore(Protocol):
    def start_run(self, work_order_id: str) -> WorkflowRun: ...

    def append_event(self, run_id: str, result: StageResult) -> None: ...

    def persist_artifact(self, run_id: str, work_order_id: str, result: StageResult) -> None: ...

    def finish_run(self, run_id: str, status: str, current_stage: str) -> None: ...


class InMemoryRunStore:
    def __init__(self) -> None:
        self.runs: dict[str, WorkflowRun] = {}
        self.events: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []

    def start_run(self, work_order_id: str) -> WorkflowRun:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = WorkflowRun(
            run_id=run_id,
            work_order_id=work_order_id,
            status="running",
            current_stage="start",
        )
        self.runs[run_id] = run
        return run

    def append_event(self, run_id: str, result: StageResult) -> None:
        self.events.append(
            {
                "run_id": run_id,
                "stage": result.stage,
                "status": result.status,
                "needs_human_review": result.needs_human_review,
                "payload": result.payload,
                "created_at": result.created_at,
            }
        )

    def persist_artifact(self, run_id: str, work_order_id: str, result: StageResult) -> None:
        self.artifacts.append(
            {
                "run_id": run_id,
                "work_order_id": work_order_id,
                "stage": result.stage,
                "payload": result.payload,
                "created_at": result.created_at,
            }
        )

    def finish_run(self, run_id: str, status: str, current_stage: str) -> None:
        run = self.runs[run_id]
        run.status = status
        run.current_stage = current_stage
        run.updated_at = utc_now_iso()


class PostgresRunStore:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required for PostgresRunStore.")
        self.database_url = database_url

    def _connect(self) -> "psycopg.Connection":
        import psycopg

        return psycopg.connect(self.database_url)

    def ensure_schema(self) -> None:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            conn.commit()

    def start_run(self, work_order_id: str) -> WorkflowRun:
        run = WorkflowRun(
            run_id=f"run_{uuid.uuid4().hex[:12]}",
            work_order_id=work_order_id,
            status="running",
            current_stage="start",
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into workflow_runs(run_id, work_order_id, status, current_stage, created_at, updated_at)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (work_order_id) do update
                    set status = excluded.status,
                        current_stage = excluded.current_stage,
                        updated_at = excluded.updated_at
                    """,
                    (
                        run.run_id,
                        run.work_order_id,
                        run.status,
                        run.current_stage,
                        run.created_at,
                        run.updated_at,
                    ),
                )
            conn.commit()
        return run

    def append_event(self, run_id: str, result: StageResult) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into workflow_events(run_id, stage, status, needs_human_review, payload, created_at)
                    values (%s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        run_id,
                        result.stage,
                        result.status,
                        result.needs_human_review,
                        json.dumps(result.payload, separators=(",", ":")),
                        result.created_at,
                    ),
                )
            conn.commit()

    def persist_artifact(self, run_id: str, work_order_id: str, result: StageResult) -> None:
        artifact_table = _artifact_table_for_stage(result.stage)
        if not artifact_table:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    insert into {artifact_table}(run_id, work_order_id, payload, created_at)
                    values (%s, %s, %s::jsonb, %s)
                    """,
                    (
                        run_id,
                        work_order_id,
                        json.dumps(result.payload, separators=(",", ":")),
                        result.created_at,
                    ),
                )
            conn.commit()

    def finish_run(self, run_id: str, status: str, current_stage: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update workflow_runs
                    set status = %s,
                        current_stage = %s,
                        updated_at = %s
                    where run_id = %s
                    """,
                    (status, current_stage, utc_now_iso(), run_id),
                )
            conn.commit()


def _artifact_table_for_stage(stage: str) -> str:
    return {
        "context": "context_packs",
        "monday_context": "context_packs",
        "draft": "drafts",
        "qa": "qa_results",
        "policy": "escalations",
        "publish": "publish_queue",
    }.get(stage, "")

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import psycopg


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _next_backoff(attempt: int) -> timedelta:
    if attempt <= 1:
        return timedelta(seconds=30)
    if attempt == 2:
        return timedelta(minutes=2)
    return timedelta(minutes=10)


@dataclass
class SwarmJob:
    job_id: str
    work_order_id: str
    payload: dict[str, Any]
    attempt: int
    status: str


class InMemorySwarmJobQueue:
    def __init__(self) -> None:
        self.jobs: list[SwarmJob] = []

    def enqueue(self, work_order_id: str, payload: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        self.jobs.append(
            SwarmJob(
                job_id=job_id,
                work_order_id=work_order_id,
                payload=payload,
                attempt=0,
                status="queued",
            )
        )
        return job_id

    def claim_next(self) -> SwarmJob | None:
        for job in self.jobs:
            if job.status == "queued":
                job.status = "running"
                job.attempt += 1
                return job
        return None

    def mark_done(self, job_id: str) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = "done"
                return

    def mark_retry(self, job_id: str, error: str, max_attempts: int = 3) -> None:
        for job in self.jobs:
            if job.job_id != job_id:
                continue
            if job.attempt >= max_attempts:
                job.status = "dead_letter"
            else:
                job.status = "queued"
            job.payload["last_error"] = error
            return

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = "dead_letter"
                job.payload["last_error"] = error
                return


class PostgresSwarmJobQueue:
    def __init__(self, database_url: str, worker_id: str = "swarm-worker-1") -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is required for PostgresSwarmJobQueue.")
        self.database_url = database_url
        self.worker_id = worker_id

    def _connect(self) -> "psycopg.Connection":
        import psycopg

        return psycopg.connect(self.database_url)

    def enqueue(self, work_order_id: str, payload: dict[str, Any]) -> str:
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into swarm_jobs (
                        job_id, work_order_id, payload, status, attempt, max_attempts, available_at, created_at, updated_at
                    )
                    values (%s, %s, %s::jsonb, 'queued', 0, 3, now(), now(), now())
                    on conflict (work_order_id) do nothing
                    """,
                    (job_id, work_order_id, json.dumps(payload, separators=(",", ":"))),
                )
            conn.commit()
        return job_id

    def claim_next(self) -> SwarmJob | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with candidate as (
                        select job_id
                        from swarm_jobs
                        where status = 'queued'
                          and available_at <= now()
                        order by available_at asc, created_at asc
                        for update skip locked
                        limit 1
                    )
                    update swarm_jobs s
                    set status = 'running',
                        attempt = s.attempt + 1,
                        locked_at = now(),
                        worker_id = %s,
                        updated_at = now()
                    from candidate c
                    where s.job_id = c.job_id
                    returning s.job_id, s.work_order_id, s.payload, s.attempt, s.status
                    """,
                    (self.worker_id,),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            return None
        return SwarmJob(
            job_id=row[0],
            work_order_id=row[1],
            payload=row[2],
            attempt=row[3],
            status=row[4],
        )

    def mark_done(self, job_id: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update swarm_jobs
                    set status = 'done',
                        locked_at = null,
                        updated_at = now()
                    where job_id = %s
                    """,
                    (job_id,),
                )
            conn.commit()

    def mark_retry(self, job_id: str, error: str, max_attempts: int = 3) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select attempt from swarm_jobs where job_id = %s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()
                if not row:
                    conn.commit()
                    return
                attempt = int(row[0])
                if attempt >= max_attempts:
                    cur.execute(
                        """
                        update swarm_jobs
                        set status = 'dead_letter',
                            last_error = %s,
                            locked_at = null,
                            updated_at = now()
                        where job_id = %s
                        """,
                        (error, job_id),
                    )
                else:
                    delay = _next_backoff(attempt)
                    cur.execute(
                        """
                        update swarm_jobs
                        set status = 'queued',
                            last_error = %s,
                            locked_at = null,
                            available_at = %s,
                            updated_at = now()
                        where job_id = %s
                        """,
                        (error, _now() + delay, job_id),
                    )
            conn.commit()

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update swarm_jobs
                    set status = 'dead_letter',
                        last_error = %s,
                        locked_at = null,
                        updated_at = now()
                    where job_id = %s
                    """,
                    (error, job_id),
                )
            conn.commit()

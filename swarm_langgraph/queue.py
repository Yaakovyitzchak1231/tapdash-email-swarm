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
    locked_at: datetime | None = None


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
                job.locked_at = _now()
                return job
        return None

    def mark_done(self, job_id: str) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = "done"
                job.locked_at = None
                return

    def mark_retry(self, job_id: str, error: str, max_attempts: int = 3) -> None:
        for job in self.jobs:
            if job.job_id != job_id:
                continue
            if job.attempt >= max_attempts:
                job.status = "dead_letter"
            else:
                job.status = "queued"
            job.locked_at = None
            job.payload["last_error"] = error
            return

    def mark_dead_letter(self, job_id: str, error: str) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.status = "dead_letter"
                job.locked_at = None
                job.payload["last_error"] = error
                return

    def recover_stale_running(self, stale_after_seconds: int = 900, max_attempts: int = 3, limit: int = 100) -> int:
        cutoff = _now() - timedelta(seconds=max(1, stale_after_seconds))
        recovered = 0
        for job in self.jobs:
            if recovered >= limit:
                break
            if job.status != "running" or not job.locked_at or job.locked_at > cutoff:
                continue
            if job.attempt >= max_attempts:
                job.status = "dead_letter"
            else:
                job.status = "queued"
            job.locked_at = None
            job.payload["last_error"] = "stale_timeout_recovered"
            recovered += 1
        return recovered


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
                    returning s.job_id, s.work_order_id, s.payload, s.attempt, s.status, s.locked_at
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
            locked_at=row[5],
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

    def recover_stale_running(self, stale_after_seconds: int = 900, max_attempts: int = 3, limit: int = 100) -> int:
        stale_after_seconds = max(1, int(stale_after_seconds))
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with candidate as (
                        select job_id, attempt
                        from swarm_jobs
                        where status = 'running'
                          and locked_at is not null
                          and locked_at <= (now() - make_interval(secs => %s))
                        order by locked_at asc
                        limit %s
                        for update skip locked
                    )
                    update swarm_jobs s
                    set status = case when c.attempt >= %s then 'dead_letter' else 'queued' end,
                        last_error = 'stale_timeout_recovered',
                        locked_at = null,
                        worker_id = null,
                        available_at = now(),
                        updated_at = now()
                    from candidate c
                    where s.job_id = c.job_id
                    returning s.job_id
                    """,
                    (stale_after_seconds, max(1, int(limit)), max_attempts),
                )
                rows = cur.fetchall()
            conn.commit()
        return len(rows)

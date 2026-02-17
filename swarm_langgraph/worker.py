from __future__ import annotations

from typing import Any, Protocol

from .supervisor import SwarmSupervisor


class SwarmJobQueue(Protocol):
    def claim_next(self): ...

    def mark_done(self, job_id: str) -> None: ...

    def mark_retry(self, job_id: str, error: str, max_attempts: int = 3) -> None: ...

    def mark_dead_letter(self, job_id: str, error: str) -> None: ...


class SwarmWorker:
    def __init__(self, supervisor: SwarmSupervisor, queue: SwarmJobQueue, max_attempts: int = 3) -> None:
        self.supervisor = supervisor
        self.queue = queue
        self.max_attempts = max_attempts

    def process_once(self) -> dict[str, Any] | None:
        job = self.queue.claim_next()
        if not job:
            return None
        try:
            result = self.supervisor.run_work_order(job.payload)
            self.queue.mark_done(job.job_id)
            return {"job_id": job.job_id, "status": "done", "result": result}
        except Exception as exc:
            if job.attempt >= self.max_attempts:
                self.queue.mark_dead_letter(job.job_id, str(exc))
                return {"job_id": job.job_id, "status": "dead_letter", "error": str(exc)}
            self.queue.mark_retry(job.job_id, str(exc), max_attempts=self.max_attempts)
            return {"job_id": job.job_id, "status": "retry", "error": str(exc)}

"""A single worker. Queued items are project ids, not models or video frames."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass

from app import db
from app.config import get_settings
from app.errors import ClipperError, JobBusyError, NotFoundError
from app.lock import lock
from app.services.pipeline import run_export, run_highlights, run_metadata, run_phase1, run_preview

logger = logging.getLogger("clipper.jobs")


@dataclass
class JobItem:
    job_id: str
    project_id: str


class JobManager:
    def __init__(self) -> None:
        self._cv = threading.Condition(lock)
        self._wait: deque[JobItem] = deque()
        self._cancelled: set[str] = set()
        self._current_project_id: str | None = None
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._cv:
            if self._thread is not None and self._thread.is_alive():
                logger.warning("Processor thread is still running.")
                return
            self._stop = False
            self._thread = threading.Thread(
                target=self._loop,
                name="clipper-processor",
                daemon=True,
            )
            self._thread.start()

    def shutdown(self) -> None:
        with self._cv:
            self._stop = True
            leftover = list(self._wait)
            self._wait.clear()
            if self._current_project_id:
                self._cancelled.add(self._current_project_id)
            self._cv.notify_all()
        for item in leftover:
            try:
                _mark_cancelled(
                    item.project_id,
                    item.job_id,
                    "Cancelled because the application is stopping.",
                )
            except Exception:
                logger.exception("Could not cancel queued job %s", item.job_id)
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def snapshot(self) -> dict:
        with self._cv:
            return {
                "running_project_id": self._current_project_id,
                "queued": len(self._wait),
            }

    def enqueue(self, project_id: str, *, kind: str = "transcribe", target_id: str | None = None) -> str:
        if kind not in {"transcribe", "highlight", "preview", "export", "metadata"}:
            raise ClipperError("Unknown job type.")
        settings = get_settings()
        waiting = {
            "highlight": "Waiting to score the transcript.",
            "preview": "Waiting to build a low-resolution preview.",
            "export": "Waiting to export the approved short.",
            "metadata": "Waiting to draft titles and a thumbnail.",
        }.get(kind, "Waiting for the processor.")
        with self._cv:
            if self._current_project_id == project_id or any(
                item.project_id == project_id for item in self._wait
            ):
                raise JobBusyError("This project is already processing.")
            inflight = (1 if self._current_project_id else 0) + len(self._wait)
            if inflight >= 1 + int(settings.max_queued_jobs):
                raise JobBusyError(
                    "The processor is busy. Only one job runs at a time. "
                    "Try again when it finishes."
                )
            job_id = db.create_job(project_id, kind=kind, target_id=target_id)
            db.update_project(
                project_id,
                status="queued",
                progress=0,
                progress_message=waiting,
                error=None,
                current_job_id=job_id,
            )
            self._wait.append(JobItem(job_id=job_id, project_id=project_id))
            self._cv.notify()
            return job_id

    def request_cancel(self, project_id: str) -> None:
        with self._cv:
            row = db.get_project(project_id)
            if row is None:
                raise NotFoundError("Project not found.")
            queued = next((item for item in self._wait if item.project_id == project_id), None)
            is_current = self._current_project_id == project_id
            if queued is None and not is_current:
                raise ClipperError("This project is not processing.")
            self._cancelled.add(project_id)
            if queued is not None and not is_current:
                self._wait = deque(item for item in self._wait if item.project_id != project_id)
                _mark_cancelled(project_id, queued.job_id, "Cancelled before it started.")
                self._cancelled.discard(project_id)
                return
            job_id = row.get("current_job_id")
            if job_id:
                db.update_job(job_id, message="Cancelling...")
            db.update_project(project_id, progress_message="Cancelling...")

    def _is_cancelled(self, project_id: str) -> bool:
        with self._cv:
            return project_id in self._cancelled

    def _loop(self) -> None:
        while True:
            with self._cv:
                while not self._wait and not self._stop:
                    self._cv.wait(timeout=0.2)
                if self._stop and not self._wait:
                    return
                if not self._wait:
                    continue
                item = self._wait.popleft()
                if item.project_id in self._cancelled:
                    self._cancelled.discard(item.project_id)
                    cancelled: JobItem | None = item
                    self._current_project_id = None
                else:
                    cancelled = None
                    self._current_project_id = item.project_id
            if cancelled is not None:
                _mark_cancelled(cancelled.project_id, cancelled.job_id, "Cancelled before it started.")
                continue
            kind = _job_kind(item.job_id)
            runners = {
                "highlight": run_highlights,
                "preview": run_preview,
                "export": run_export,
                "metadata": run_metadata,
            }
            runner = runners.get(kind, run_phase1)
            try:
                runner(
                    item.project_id,
                    item.job_id,
                    should_cancel=lambda project_id=item.project_id: self._is_cancelled(project_id),
                )
            except Exception:
                logger.exception("Worker crashed project=%s", item.project_id)
                try:
                    if kind in {"highlight", "preview", "export", "metadata"}:
                        db.fail_render(
                            item.project_id,
                            item.job_id,
                            error="The processor crashed. The transcript was kept.",
                        )
                    else:
                        db.fail_job(
                            item.project_id,
                            item.job_id,
                            error="The processor crashed. See data/logs/app.log.",
                        )
                except Exception:
                    logger.exception("Could not record the processor crash")
            finally:
                with self._cv:
                    if self._current_project_id == item.project_id:
                        self._current_project_id = None
                    self._cancelled.discard(item.project_id)


def _job_kind(job_id: str) -> str:
    row = db.get_job(job_id)
    if not row:
        return "transcribe"
    return str(row.get("kind") or "transcribe")


def _mark_cancelled(project_id: str, job_id: str, message: str) -> None:
    kind = _job_kind(job_id)
    if kind == "highlight":
        db.cancel_highlight(project_id, job_id, message)
        return
    if kind in {"preview", "export", "metadata"}:
        db.cancel_render(project_id, job_id, message)
        return
    db.cancel_job(project_id, job_id, message=message)


job_manager = JobManager()

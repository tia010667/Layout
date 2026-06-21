"""In-memory job store and lifecycle management."""

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.config import settings


@dataclass
class JobRecord:
    job_id: str
    status: str = "idle"
    template_path: str = ""
    content_path: str = ""
    template_filename: str = ""
    content_filename: str = ""
    retry_count: int = 0
    error: Optional[str] = None
    coverage_rate: Optional[float] = None
    error_count: Optional[int] = None
    warning_count: Optional[int] = None
    docx_buffer: Optional[bytes] = None
    preview_html: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    task_handle: Optional[asyncio.Task] = None


class JobManager:
    """Thread-safe in-memory job store."""

    def __init__(self):
        self._jobs: dict[str, JobRecord] = {}
        self._cleanup_task: Optional[asyncio.Task] = None

    def create_job(self) -> JobRecord:
        """Create a new job with UUID and allocated directories."""
        job_id = uuid.uuid4().hex[:12]
        job = JobRecord(job_id=job_id)

        # Create job-scoped directories
        upload_dir = Path(settings.upload_dir) / job_id
        output_dir = Path(settings.output_dir) / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[JobRecord]:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def update_job(self, job_id: str, **kwargs) -> Optional[JobRecord]:
        """Update job fields."""
        job = self._jobs.get(job_id)
        if job:
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
        return job

    def delete_job(self, job_id: str) -> bool:
        """Delete a job and its files."""
        job = self._jobs.pop(job_id, None)
        if job:
            # Cancel running task
            if job.task_handle and not job.task_handle.done():
                job.task_handle.cancel()

            # Clean up files
            import shutil
            upload_dir = Path(settings.upload_dir) / job_id
            output_dir = Path(settings.output_dir) / job_id
            if upload_dir.exists():
                shutil.rmtree(upload_dir, ignore_errors=True)
            if output_dir.exists():
                shutil.rmtree(output_dir, ignore_errors=True)
            return True
        return False

    async def cleanup_old_jobs(self, max_age_hours: int = 24):
        """Remove jobs older than max_age_hours."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        to_delete = [
            jid for jid, job in self._jobs.items()
            if job.created_at < cutoff
        ]
        for jid in to_delete:
            self.delete_job(jid)

    def start_cleanup_scheduler(self, interval_minutes: int = 60):
        """Start periodic cleanup of old jobs."""
        async def _cleanup_loop():
            while True:
                await asyncio.sleep(interval_minutes * 60)
                await self.cleanup_old_jobs()

        self._cleanup_task = asyncio.create_task(_cleanup_loop())


# Singleton instance
job_manager = JobManager()

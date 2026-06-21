"""API routes - thin layer that delegates to the Agent."""

import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response

from app.api.job_manager import job_manager
from app.api.schemas import (
    ConfigStatusResponse,
    ErrorResponse,
    JobStatusResponse,
    ProcessRequest,
    ProcessResponse,
    UploadResponse,
)
from app.config import settings

router = APIRouter()

ALLOWED_TEMPLATE_EXTENSIONS = {".docx", ".pdf"}
ALLOWED_CONTENT_EXTENSIONS = {".docx"}


@router.get("/config-status", response_model=ConfigStatusResponse)
async def config_status():
    """Check if the AI provider is configured."""
    api_key = settings.deepseek_api_key
    configured = bool(api_key and api_key != "sk-your-deepseek-key-here")
    return ConfigStatusResponse(
        configured=configured,
        provider=settings.ai_provider,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload(
    template: UploadFile = File(...),
    content: UploadFile = File(...),
):
    """Upload template and content files. Returns a job_id."""
    # Validate template extension
    template_ext = Path(template.filename).suffix.lower()
    if template_ext not in ALLOWED_TEMPLATE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Template must be .docx or .pdf, got {template_ext}",
        )

    # Validate content extension
    content_ext = Path(content.filename).suffix.lower()
    if content_ext not in ALLOWED_CONTENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Content must be .docx, got {content_ext}",
        )

    # Validate template file size
    template_data = await template.read()
    if len(template_data) > settings.max_template_size:
        raise HTTPException(
            status_code=413,
            detail=f"Template too large ({len(template_data)} bytes). "
                   f"Max: {settings.max_template_size} bytes",
        )

    # Validate content file size
    content_data = await content.read()
    if len(content_data) > settings.max_content_size:
        raise HTTPException(
            status_code=413,
            detail=f"Content too large ({len(content_data)} bytes). "
                   f"Max: {settings.max_content_size} bytes",
        )

    # Create job
    job = job_manager.create_job()

    # Save files
    template_path = Path(settings.upload_dir) / job.job_id / template.filename
    content_path = Path(settings.upload_dir) / job.job_id / content.filename

    template_path.write_bytes(template_data)
    content_path.write_bytes(content_data)

    # Update job record
    job_manager.update_job(
        job.job_id,
        template_path=str(template_path),
        content_path=str(content_path),
        template_filename=template.filename,
        content_filename=content.filename,
    )

    return UploadResponse(
        job_id=job.job_id,
        template_filename=template.filename,
        content_filename=content.filename,
    )


@router.post("/process", response_model=ProcessResponse)
async def process(request: ProcessRequest):
    """Start the Agent graph run for a given job."""
    job = job_manager.get_job(request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.template_path or not job.content_path:
        raise HTTPException(status_code=400, detail="Job has no uploaded files")

    # Launch agent in background
    from app.agent.graph import run_agent
    task = run_agent(job.job_id)
    job_manager.update_job(job.job_id, task_handle=task)

    return ProcessResponse(job_id=job.job_id, status="started")


@router.get("/job/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: str):
    """Poll the current status of a job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        retry_count=job.retry_count,
        error=job.error,
        template_filename=job.template_filename,
        content_filename=job.content_filename,
        coverage_rate=job.coverage_rate,
        error_count=job.error_count,
        warning_count=job.warning_count,
    )


@router.get("/job/{job_id}/preview")
async def job_preview(job_id: str):
    """Get the HTML preview of the generated document."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    if not job.preview_html:
        raise HTTPException(status_code=404, detail="No preview available")

    return Response(content=job.preview_html, media_type="text/html")


@router.get("/job/{job_id}/download")
async def job_download(job_id: str):
    """Download the generated .docx file."""
    import logging
    logger = logging.getLogger("formatai")

    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed yet")

    # Try buffer first, fall back to reading from disk
    docx_buffer = job.docx_buffer
    if not docx_buffer:
        # Read from the output file on disk
        output_path = Path(settings.output_dir) / job_id
        if output_path.exists():
            docx_files = list(output_path.glob("formatted_*.docx"))
            if docx_files:
                logger.info(f"Reading docx from disk: {docx_files[0]}")
                docx_buffer = docx_files[0].read_bytes()

    if not docx_buffer:
        raise HTTPException(status_code=404, detail="No document available")

    filename = f"formatted_{job.content_filename or 'document'}"
    if not filename.endswith(".docx"):
        filename = filename.rsplit(".", 1)[0] + ".docx"

    # URL-encode filename for non-ASCII characters
    from urllib.parse import quote
    safe_filename = quote(filename)

    return Response(
        content=docx_buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
    )


@router.delete("/job/{job_id}")
async def job_delete(job_id: str):
    """Clean up a job and its files."""
    if job_manager.delete_job(job_id):
        return {"status": "deleted", "job_id": job_id}
    raise HTTPException(status_code=404, detail="Job not found")

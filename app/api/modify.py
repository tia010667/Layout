"""API routes for natural-language format modification."""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agent.tools.docx_modifier import apply_operations
from app.agent.tools.docx_snapshot import build_snapshot
from app.agent.tools.format_instructor import (
    interpret_instruction,
    operation_to_dict,
)
from app.agent.tools.preview_builder import build_preview_html
from app.api.job_manager import job_manager
from app.config import settings

logger = logging.getLogger("formatai")

router = APIRouter()


@router.post("/modify")
async def modify_document(
    instruction: str = Form(...),
    source_job_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """Apply a natural-language formatting instruction to a document.

    The source document comes either from an uploaded file or from an
    existing job (a prior formatting run or a previous modification).
    Returns a new job_id whose preview/download can be fetched via the
    standard job endpoints.
    """
    # 1. Resolve source docx bytes
    source_bytes = await _load_source_docx(file, source_job_id)
    if len(source_bytes) > settings.max_content_size:
        raise HTTPException(
            status_code=413,
            detail=f"Document too large ({len(source_bytes)} bytes). Max: {settings.max_content_size}",
        )

    # 2. Snapshot → LLM interpretation → operations
    snapshot = build_snapshot(source_bytes)

    try:
        result = await interpret_instruction(snapshot, instruction)
    except Exception as e:
        logger.exception("Instruction interpretation failed")
        raise HTTPException(status_code=422, detail=str(e))

    operations = [operation_to_dict(op) for op in result.operations]

    # 3. Apply operations
    new_bytes = apply_operations(source_bytes, operations)

    # 4. Build preview + persist as a new job
    preview_html = build_preview_html(new_bytes)

    job = job_manager.create_job()
    job_manager.update_job(
        job.job_id,
        status="completed",
        docx_buffer=new_bytes,
        preview_html=preview_html,
        content_filename=f"modified_{job.job_id}.docx",
    )

    return {
        "job_id": job.job_id,
        "summary": result.summary or "已完成格式调整",
        "operation_count": len(operations),
        "preview_html": preview_html,
    }


async def _load_source_docx(
    file: Optional[UploadFile],
    source_job_id: Optional[str],
) -> bytes:
    """Resolve the source document bytes from an upload or an existing job."""
    if file is not None:
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        return data

    if source_job_id:
        job = job_manager.get_job(source_job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Source job not found")

        if job.docx_buffer:
            return job.docx_buffer

        output_path = Path(settings.output_dir) / source_job_id
        if output_path.exists():
            docx_files = list(output_path.glob("formatted_*.docx"))
            if docx_files:
                return docx_files[0].read_bytes()

        raise HTTPException(status_code=404, detail="Source document not available")

    raise HTTPException(status_code=400, detail="Provide a file or source_job_id")

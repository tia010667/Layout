"""Node 6: Package output — save .docx to disk and build HTML preview."""

import os
from pathlib import Path

from app.agent.state import AgentState
from app.agent.tools.preview_builder import build_preview_html
from app.config import settings


async def output_node(state: AgentState) -> dict:
    """Final node: save the .docx buffer to disk and generate HTML preview.

    Writes the generated .docx to output/{job_id}/output.docx and
    builds an HTML preview string for frontend display.
    """
    docx_buffer = state.get("docx_buffer")
    job_id = state.get("job_id", "unknown")
    content_filename = state.get("content_filename", "document.docx")

    if not docx_buffer:
        return {"error": "No docx buffer to output", "status": "failed"}

    try:
        # Save to disk
        output_dir = Path(settings.output_dir) / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        output_name = f"formatted_{content_filename}"
        if not output_name.endswith(".docx"):
            output_name = output_name.rsplit(".", 1)[0] + ".docx"

        output_path = output_dir / output_name
        output_path.write_bytes(docx_buffer)

        # Build HTML preview
        preview_html = build_preview_html(docx_buffer)

        return {
            "preview_html": preview_html,
            "docx_buffer": docx_buffer,
            "status": "completed",
        }

    except Exception as e:
        return {
            "error": f"[output] {type(e).__name__}: {str(e)}",
            "status": "failed",
        }

"""Node 1: Parse template file to extract formatting rules."""

import os

from app.agent.state import AgentState
from app.agent.tools.docx_parser import parse_docx_template
from app.agent.tools.pdf_parser import parse_pdf_template


async def parse_template(state: AgentState) -> dict:
    """Parse the template file (.docx or .pdf) and extract all format rules.

    Reads the template from template_path, routes to the appropriate
    parser based on file extension, and populates template_analysis.
    """
    template_path = state.get("template_path", "")

    if not template_path or not os.path.exists(template_path):
        return {
            "error": "Template file not found",
            "status": "failed",
        }

    try:
        ext = os.path.splitext(template_path)[1].lower()

        if ext == ".docx":
            analysis = parse_docx_template(template_path)
        elif ext == ".pdf":
            analysis = parse_pdf_template(template_path)
        else:
            return {
                "error": f"Unsupported template format: {ext}",
                "status": "failed",
            }

        return {
            "template_analysis": analysis,
            "status": "analyzing_content",
        }

    except Exception as e:
        return {
            "error": f"[parse_template] {type(e).__name__}: {str(e)}",
            "status": "failed",
        }

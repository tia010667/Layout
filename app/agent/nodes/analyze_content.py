"""Node 2: Analyze content file to extract paragraph structure."""

import os

from app.agent.state import AgentState
from app.agent.tools.content_analyzer import analyze_content_docx


async def analyze_content(state: AgentState) -> dict:
    """Analyze the content .docx file and extract paragraph structure.

    Reads the content file from content_path, extracts all paragraphs
    with their text, current formatting, and semantic roles.
    """
    content_path = state.get("content_path", "")

    if not content_path or not os.path.exists(content_path):
        return {
            "error": "Content file not found",
            "status": "failed",
        }

    try:
        structure = analyze_content_docx(content_path)

        # Embed the content path so later nodes can read inline formatting
        structure["_content_path"] = content_path

        return {
            "content_structure": structure,
            "status": "matching_styles",
        }

    except Exception as e:
        return {
            "error": f"[analyze_content] {type(e).__name__}: {str(e)}",
            "status": "failed",
        }

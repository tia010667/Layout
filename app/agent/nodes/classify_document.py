"""Node 2.5: Classify the document type and set the formatting strategy.

Runs after parse_template + analyze_content (both template_analysis and
content_structure are already in state). Classifies the pair into
copy / text_flow / table_form and stores the mode so the graph can route
copy jobs straight to generation, skipping LLM matching and verification.
"""

import logging
import sys

from app.agent.state import AgentState
from app.agent.tools.document_classifier import classify_document as classify_pair

logger = logging.getLogger(__name__)


async def classify_document(state: AgentState) -> dict:
    """Classify template+content into copy / text_flow / table_form."""
    template_path = state.get("template_path")
    content_path = state.get("content_path")

    if not template_path or not content_path:
        return {
            "error": "Missing template/content path for classification",
            "status": "failed",
        }

    result = classify_pair(template_path, content_path)
    mode = result["mode"]

    print(f"  [classify_document] mode={mode} ({result['reason']})", flush=True)
    logger.info(f"Document classified as '{mode}': {result['reason']}")

    return {
        "document_mode": mode,
        "classification": result,
        "status": "generating_docx" if mode == "copy" else "matching_styles",
    }

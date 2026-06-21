"""Node 5: Generate the final formatted .docx from the verified style mapping.

Uses the template .docx as the base document — preserves all its style
definitions exactly — and adds content paragraphs with assigned styles.
"""

from app.agent.state import AgentState
from app.agent.tools.docx_generator import generate_docx_from_mapping


async def generate_docx(state: AgentState) -> dict:
    """Generate a .docx file using the template as the base document.

    Opens the template .docx, clears its body, and adds content
    paragraphs with the style names assigned by the LLM. This
    ensures 100% accurate formatting.
    """
    template_path = state.get("template_path")
    style_mapping = state.get("style_mapping")
    content_structure = state.get("content_structure")

    if not template_path:
        return {"error": "No template path available", "status": "failed"}
    if not style_mapping:
        return {"error": "No style mapping available", "status": "failed"}
    if not content_structure:
        return {"error": "No content structure available", "status": "failed"}

    try:
        docx_buffer = generate_docx_from_mapping(
            template_path=template_path,
            style_mapping=style_mapping,
            content_structure=content_structure,
            template_analysis=state.get("template_analysis"),
        )

        return {
            "docx_buffer": docx_buffer,
            "status": "building_preview",
        }

    except Exception as e:
        return {
            "error": f"[generate_docx] {type(e).__name__}: {str(e)}",
            "status": "failed",
        }

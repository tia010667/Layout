"""AgentState — the state object that flows through every LangGraph node."""

from typing import Optional, TypedDict


class AgentState(TypedDict, total=False):
    """State shared across all nodes in the FormatAI agent graph.

    Each node reads from this state and returns a partial dictionary
    to update only its relevant keys. LangGraph merges the partial
    updates into the full state automatically.
    """

    # Input paths
    template_path: str
    content_path: str
    template_filename: str
    content_filename: str

    # Parsed data
    template_analysis: Optional[dict]   # Format rules extracted from template
    content_structure: Optional[dict]   # Paragraph structure + semantic roles

    # Document classification
    document_mode: str                  # "copy" | "text_flow" | "table_form"
    classification: Optional[dict]      # Full classification result (mode, reason, fingerprints)

    # LLM output
    style_mapping: Optional[dict]       # Content element → Template style mapping

    # Verification
    verification_result: Optional[dict]  # Pass/fail + error details + coverage
    retry_count: int                    # Number of retries attempted
    verification_feedback: Optional[str]  # Error feedback for retry loop
    max_retries: int                    # Maximum retry attempts (default 3)

    # Final output
    docx_buffer: Optional[bytes]         # Generated .docx file bytes
    preview_html: Optional[str]          # HTML preview string

    # Execution metadata
    error: Optional[str]                # Terminal error message
    status: str                         # Current stage label
    job_id: str                         # Job identifier for external tracking
